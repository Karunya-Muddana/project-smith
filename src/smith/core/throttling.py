"""
Global Throttling & Circuit Breaker Module
------------------------------------------
Provides a singleton rate limiter and circuit breaker to manage 
traffic to external APIs (Gemini, Groq) globally across the daemon.
"""

import time
import threading
import random
import logging
from typing import Dict, Optional
from dataclasses import dataclass

from smith.config import config

logger = logging.getLogger("smith.throttling")

@dataclass
class RateLimitConfig:
    rpm: int
    tpm: int
    burst: int = 1

class TokenBucket:
    """
    Thread-safe Token Bucket implementation for rate limiting.
    Manages both Requests (RPM) and Tokens (TPM).
    """
    def __init__(self, rpm: int, tpm: int, burst: int = 1):
        self.max_tokens_rpm = burst
        self.tokens_rpm = burst
        self.max_tokens_tpm = tpm
        self.tokens_tpm = tpm
        
        self.rpm_fill_rate = rpm / 60.0
        self.tpm_fill_rate = tpm / 60.0
        
        self.last_update = time.time()
        self.lock = threading.Lock()

    def _refill(self):
        now = time.time()
        elapsed = now - self.last_update
        if elapsed <= 0:
            return
            
        # Refill Request Tokens
        new_rpm = elapsed * self.rpm_fill_rate
        self.tokens_rpm = min(self.max_tokens_rpm, self.tokens_rpm + new_rpm)
        
        # Refill/Use Usage Tokens (TPM refill logic - simplified to just refill)
        # Note: TPM is usually consumption based. We refill up to limit.
        new_tpm = elapsed * self.tpm_fill_rate
        self.tokens_tpm = min(self.max_tokens_tpm, self.tokens_tpm + new_tpm)
        
        self.last_update = now

    def acquire(self, estimated_tokens: int = 100) -> float:
        """
        Try to acquire a slot. Returns float seconds to wait. 
        0.0 means go ahead. > 0 means sleep that amount.
        """
        with self.lock:
            self._refill()
            
            # Check basic availability
            if self.tokens_rpm < 1.0:
                needed = 1.0 - self.tokens_rpm
                wait = needed / self.rpm_fill_rate
                return max(0.1, wait)
                
            if self.tokens_tpm < estimated_tokens:
                 needed = estimated_tokens - self.tokens_tpm
                 wait = needed / self.tpm_fill_rate
                 return max(0.1, wait)
            
            # Consume
            self.tokens_rpm -= 1.0
            self.tokens_tpm -= estimated_tokens
            return 0.0

    def penalize(self, seconds: float = 5.0):
        """
        Artificially drain tokens or advance time to force a pause.
        """
        with self.lock:
            # Drain all RPM tokens to force a wait
            self.tokens_rpm = -1.0 * (seconds * self.rpm_fill_rate)
            logger.warning(f"Throttler Penalized: Global pause for ~{seconds}s")

class CircuitBreaker:
    """
    Manages state for a provider (Closed -> Open -> Half-Open).
    """
    def __init__(self, name: str, failure_threshold: int = 3, recovery_timeout: int = 300):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        
        self.failures = 0
        self.state = "CLOSED" # CLOSED, OPEN
        self.last_failure_time = 0.0
        self.lock = threading.Lock()

    def report_failure(self):
        with self.lock:
            self.failures += 1
            self.last_failure_time = time.time()
            if self.failures >= self.failure_threshold:
                if self.state == "CLOSED":
                    logger.warning(f"Circuit Breaker OPENED for {self.name} (Failures: {self.failures})")
                    self.state = "OPEN"

    def report_success(self):
        with self.lock:
            if self.state == "OPEN":
                # Check execution probe? For now, success closes it.
                logger.info(f"Circuit Breaker CLOSED for {self.name} (Recovered)")
            self.state = "CLOSED"
            self.failures = 0

    def is_open(self) -> bool:
        with self.lock:
            if self.state == "CLOSED":
                return False
            
            # Check recovery timeout
            elapsed = time.time() - self.last_failure_time
            if elapsed > self.recovery_timeout:
                logger.info(f"Circuit Breaker {self.name} probing (Half-Open)...")
                return False # Let one through to test
            
            return True

class GlobalThrottler:
    """
    Singleton manager for all rate limits and circuits.
    """
    def __init__(self):
        self.limiters: Dict[str, TokenBucket] = {}
        self.circuits: Dict[str, CircuitBreaker] = {}
        
        # Initialize Groq
        self.limiters["groq"] = TokenBucket(
            rpm=config.groq_rpm,
            tpm=config.groq_tpm,
            burst=5 # Allow more burst for fallback
        )
        # Groq circuit breaker
        self.circuits["groq"] = CircuitBreaker("groq", failure_threshold=10, recovery_timeout=30)

    def wait_for_slot(self, provider: str, estimated_tokens: int = 100):
        """
        Blocks until a slot is available for the provider.
        """
        limiter = self.limiters.get(provider)
        if not limiter:
            return
            
        while True:
            wait_time = limiter.acquire(estimated_tokens)
            if wait_time <= 0.0:
                break
            # Add jitter to wait time to prevent synchronized wakeups
            jitter = random.uniform(0.0, 0.5)
            total_wait = min(wait_time + jitter, 30.0) # Cap wait
            logger.debug(f"RateLimit ({provider}): waiting {total_wait:.2f}s")
            time.sleep(total_wait)
            
    def check_circuit(self, provider: str) -> bool:
        """
        Returns True if circuit is OPEN (blocked), False if OK.
        """
        cb = self.circuits.get(provider)
        if not cb:
            return False
        return cb.is_open()
    
    def report_result(self, provider: str, success: bool):
        cb = self.circuits.get(provider)
        if not cb:
            return
        if success:
            cb.report_success()
        else:
            cb.report_failure()

    def report_429(self, provider: str, wait_seconds: float = 5.0):
        """
        Notify that a 429 occurred, penalizing the bucket globally.
        """
        limiter = self.limiters.get(provider)
        if limiter:
            limiter.penalize(wait_seconds)

# Singleton Instance
throttler = GlobalThrottler()
