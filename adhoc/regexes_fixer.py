import os
import json
import re


def process_json_files(directory):
    # Pattern to match filenames starting with "regexes_" and ending with ".json"
    pattern = re.compile(r"^regexes_.*\.json$")

    # Count for reporting
    processed_files = 0

    # Walk through the directory
    for root, _, files in os.walk(directory):
        for filename in files:
            # Check if the filename matches our pattern
            if pattern.match(filename):
                filepath = os.path.join(root, filename)
                print(f"Processing file: {filepath}")

                try:
                    # Load the JSON content
                    with open(filepath, "r", encoding="utf-8") as file:
                        data = json.load(file)

                    # Make sure it's a dictionary
                    if not isinstance(data, dict):
                        print(
                            f"  Warning: {filepath} does not contain a dictionary. Skipping."
                        )
                        continue

                    # Replace spaces with '\s' in all values
                    modified = False
                    for key, value in data.items():
                        if isinstance(value, str) and " " in value:
                            data[key] = value.replace(" ", "\\s")
                            modified = True

                    # Save the modified content only if changes were made
                    if modified:
                        with open(filepath, "w", encoding="utf-8") as file:
                            json.dump(data, file, ensure_ascii=False, indent=4)
                        print(f"  Updated {filepath}")
                    else:
                        print(f"  No spaces found in values of {filepath}")

                    processed_files += 1

                except json.JSONDecodeError:
                    print(f"  Error: {filepath} is not a valid JSON file. Skipping.")
                except Exception as e:
                    print(f"  Error processing {filepath}: {str(e)}")

    print(f"\nSummary: Processed {processed_files} JSON files.")


if __name__ == "__main__":
    # Get the directory from user
    directory = input("Enter the directory path to search: ")

    # Validate directory exists
    if not os.path.isdir(directory):
        print(f"Error: '{directory}' is not a valid directory.")
    else:
        process_json_files(directory)
