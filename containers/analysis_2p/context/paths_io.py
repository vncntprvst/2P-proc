import json
import argparse
import os

def read_path_file(path_file, field_name='None'):
    data_paths = []
    export_paths = []
    params_files = []
    zstack_paths = []
    z_params_files = []
    subject = ''
    file_date = ''
    # If json format
    if path_file.endswith('.json'):
        with open(path_file) as f:
            # content = f.read()
            # print(content)  # To check what is being read
            data = json.load(f)
        if field_name != 'None':
            data_paths = data[field_name]
        else:
            data_paths = data['data_paths']
            export_paths = data['export_paths']
        if 'params_files' in data:
            params_files = data['params_files']
        if 'zstack_paths' in data:
            zstack_paths = data['zstack_paths']
        if 'z_params_files' in data:
            z_params_files = data['z_params_files']
        if 'subject' in data:
            subject = data['subject']
            # print('Subject: ' + subject)
        if 'date' in data:
            file_date = data['date']
            # file_date = file_date.split('-')  # split the date string into a list [YYYY, MM, DD]
            # file_date = file_date[2] + file_date[1] + file_date[0]  # rearrange to DDMMYYYY
            # print('Date: ' + file_date)

    # If csv format
    else:
        with open(path_file) as f:
            data = f.readlines()
            data_paths = data[0].strip()
            export_paths = data[1].strip()
            params_files = data[2].strip()
            #  Check if there are zstack paths and z_params_files
            if len(data) > 3:
                zstack_paths = data[3].strip()
                z_params_files = data[4].strip()
    
    return data_paths, export_paths, params_files, zstack_paths, z_params_files, subject, file_date

def check_filesystem(data_path):
    # if it's a json file, open it and read the data paths
    if data_path.endswith('.json'):
        data_path = read_path_file(data_path)[0]
        
    # if data_path is a dictionary or a list, get the first data_path
    if isinstance(data_path, dict) or isinstance(data_path, list):
        data_path = data_path[0]
    # print('Data path: ' + data_path)
        
    if not os.path.exists(data_path):
        print('Data path not found. Check the path.')
        return
        
    # check if data files are on /nese (i.e., path starts with /nese)
    if data_path.startswith('/nese'):
        filesystem = 'nese'
    elif data_path.startswith('/om') | data_path.startswith('/om2'):
        filesystem = 'om'
    elif data_path.startswith('/mnt'):
        filesystem = 'raid_storage'
    else:
        filesystem = 'local'
    
    return filesystem

def read_data_paths(file_path, field_name, shell_type='python'):
    with open(file_path, "r") as f:
        data = json.load(f)
    
    if field_name not in data:
        return []  # Return empty list instead of printing messages

    data_paths = data[field_name]

    if shell_type == 'bash':
        return "\n".join(data_paths)  # Use newline delimiter for Bash

    return data_paths       
          
def get_common_dir(file_path, field_name):
    data_paths = read_data_paths(file_path, field_name)

    # if the data_paths is a list with more than one element
    if isinstance(data_paths, list) and len(data_paths) > 1:
        common_dir = os.path.commonpath(data_paths)
    # if it's a single file in a list, return its directory
    elif isinstance(data_paths, list) and len(data_paths) == 1:
        common_dir = os.path.dirname(data_paths[0])
    # if the data_paths is a dictionary with a 'log_path' key
    elif isinstance(data_paths, dict) and 'log_path' in data_paths:
        common_dir = data_paths['log_path']
    else:
        common_dir = None
        
    return common_dir

def update_remote_paths(path_file, old_paths, new_paths, overwrite=True):
    # Ensure old_paths and new_paths are lists
    if not isinstance(old_paths, list):
        old_paths = [old_paths]
    if not isinstance(new_paths, list):
        new_paths = [new_paths]
    
    if len(old_paths) != len(new_paths):
        raise ValueError("old_paths and new_paths must have the same length")

    # Read the JSON file
    with open(path_file, 'r') as f:
        try:
            data = json.load(f)
        except Exception as e:
            print(f"\nCheck path file {path_file}.\nThere is probably a typo.\n")
            print(f"\nLoading file content failed with error: {e}\n")

    # Update paths
    for old_path, new_path in zip(old_paths, new_paths):
        for key, value in data.items():
            if isinstance(value, str):
                data[key] = value.replace(old_path, new_path)
            elif isinstance(value, list):
                data[key] = [v.replace(old_path, new_path) if isinstance(v, str) else v for v in value]
            elif isinstance(value, dict):
                data[key] = {k: v.replace(old_path, new_path) if isinstance(v, str) else v for k, v in value.items()}

    # Update path_file's path only if old_path is actually in it
    for old_path, new_path in zip(old_paths, new_paths):
        if old_path in path_file:
            path_file = path_file.replace(old_path, new_path)

    # Write the updated data back to the file
    if overwrite:
        with open(path_file, 'w') as f:
            json.dump(data, f, indent=4)
            
    return path_file       

def generate_target_paths(source_paths, target_fs, shell_type='python', field_name='None'):
    if source_paths.endswith('.json'):
        source_paths = read_path_file(source_paths, field_name)[0]

    if isinstance(source_paths, str):
        source_paths = source_paths.replace('[', '').replace(' ', ',').replace(']', '').split(',')

    if not source_paths:
        raise ValueError("No valid source paths found.")

    target_paths = []
    for source_path in source_paths:
        path_parts = source_path.strip("/").split("/")
        
        # Extract components dynamically
        # Construct the target path
        if field_name == 'export_paths':
            subject = path_parts[-4]  # Subject (e.g., 2P13)
            session_date = path_parts[-3]  # Session date (e.g., 20240903)
            run_name = path_parts[-2]  # Run name (e.g., TSeries-09032024-0952-001)
            method = path_parts[-1]  # Method (e.g., mesmerize)
            target_path = f"{target_fs}/{subject}/{session_date}/{run_name}/{method}"
        else:
            subject = path_parts[-3]  # Subject (e.g., 2P13)
            session_date = path_parts[-2]  # Session date (e.g., 20240903)
            run_name = path_parts[-1]  # Run name (e.g., TSeries-09032024-0952-001)
            target_path = f"{target_fs}/{subject}/{session_date}/{run_name}"
        os.makedirs(target_path, exist_ok=True)  # Ensure directory exists

        target_paths.append(target_path)

    if shell_type == 'bash':
        target_paths = '\n'.join(target_paths) # Ensure newline-separated output for Bash

    return target_paths

import json

def update_path_file(path_file, target_path_file, data_paths, export_paths=None, params_files=None, zstack_paths=None, z_params_files=None):
    """ Updates the target path file with new data paths, export paths, and optional parameters. """
    
    # Load existing path file
    with open(path_file, 'r') as f:
        data = json.load(f)
        
    # Convert '__NONE__' strings to None
    export_paths = None if export_paths == '__NONE__' else export_paths
    params_files = None if params_files == '__NONE__' else params_files
    zstack_paths = None if zstack_paths == '__NONE__' else zstack_paths
    z_params_files = None if z_params_files == '__NONE__' else z_params_files

    # Ensure optional fields are updated correctly
    export_paths = export_paths if export_paths is not None else data.get('export_paths', [])
    params_files = params_files if params_files is not None else data.get('params_files', [])
    zstack_paths = zstack_paths if zstack_paths is not None else data.get('zstack_paths', [])
    z_params_files = z_params_files if z_params_files is not None else data.get('z_params_files', [])

    # Convert Bash arrays (strings) to Python lists if needed
    def parse_list(value):
        if isinstance(value, str):
            # Remove any extraneous brackets and then split on newline
            return value.replace('[', '').replace(']', '').splitlines()
        return value

    data_paths = parse_list(data_paths)
    export_paths = parse_list(export_paths)
    zstack_paths = parse_list(zstack_paths)

    # Update the dictionary
    data['data_paths'] = data_paths
    data['export_paths'] = export_paths
    data['params_files'] = params_files
    data['zstack_paths'] = zstack_paths
    data['z_params_files'] = z_params_files

    # Write to the new target path file
    if target_path_file is None:
        print('Overwriting original path file')
        target_path_file = path_file

    with open(target_path_file, 'w') as f:
        json.dump(data, f, indent=4)

    print(f'Updated path file saved to {target_path_file}')

def transfer_data(source_paths, target_paths):
    if isinstance(source_paths, str):
        source_paths = source_paths.replace('[', '').replace(' ', ',').replace(']', '').split(',')
        # print('Source paths now: ' + str(source_paths))
    if isinstance(target_paths, str):
        target_paths = target_paths.replace('[', '').replace(' ', ',').replace(']', '').split(',')
        # print('Target paths now: ' + str(target_paths))
        
    for source_path, target_path in zip(source_paths, target_paths):        
        # copy data from source to target
        if os.path.exists(source_path):
            print('Copying data from ' + source_path + ' to ' + target_path)
            os.system('rsync -azP ' + source_path + ' ' + target_path)
        else:
            print('Source path does not exist')
        
    return
          
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('path_file', nargs='+', help='Input file containing paths to data and export folders')
    args = parser.parse_args()

    path_file = args.path_file[0]
    read_path_file(path_file)
      
if __name__ == '__main__':
    main()