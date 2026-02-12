"""
Test script to verify tool registration in MongoDB and save output to file
"""
import os
from pymongo import MongoClient

# Configuration
MONGO_URI = os.getenv(
    "MONGO_URI", "mongodb://root:password@localhost:27017/?authSource=admin"
)
DB_NAME = "project_smith"
COLLECTION_NAME = "tools"

def main():
    output_lines = []
    try:
        # Connect to MongoDB
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.server_info()
        output_lines.append("[OK] Connected to MongoDB successfully\n")
        
        # Get the tools collection
        collection = client[DB_NAME][COLLECTION_NAME]
        
        # Count total tools
        total_tools = collection.count_documents({})
        output_lines.append(f"\n[INFO] Total tools registered: {total_tools}\n")
        
        # List all registered tools
        if total_tools > 0:
            output_lines.append("\n[LIST] Registered tools:\n")
            output_lines.append("-" * 80 + "\n")
            for tool in collection.find({}):
                name = tool.get('name', 'Unknown')
                module = tool.get('module', 'Unknown')
                description = tool.get('description', 'No description')
                function = tool.get('function', 'Unknown')
                output_lines.append(f"\n  [TOOL] {name}\n")
                output_lines.append(f"     Module: {module}\n")
                output_lines.append(f"     Function: {function}\n")
                output_lines.append(f"     Description: {description}\n")
        else:
            output_lines.append("\n[WARN] No tools found in the registry!\n")
            
    except Exception as e:
        output_lines.append(f"[ERROR] Error: {e}\n")
    
    # Write to file
    with open('tool_registry_report.txt', 'w', encoding='utf-8') as f:
        f.writelines(output_lines)
    
    # Also print to console
    print(''.join(output_lines))
    print("\n[INFO] Report saved to tool_registry_report.txt")

if __name__ == "__main__":
    main()
