#!/bin/bash

SERVER_DIR="./servers"

declare -A ENV_GROUPS=(
  [PROD]="prod"
  [NONPROD]="nonprod"
)

# Recursively extract all groups and their hosts from a hosts.yml file
extract_groups_and_hosts() {
  local file=$1
  local current_group=""
  local group=""
  local indent=0

  declare -A group_to_hosts=()
  declare -A group_stack=()

  while IFS= read -r line; do
    # Normalize indentation
    local leading_spaces=$(echo "$line" | sed -E 's/^([ ]*).*/\1/' | wc -c)
    local trimmed=$(echo "$line" | sed -E 's/^ +//')

    # Match group name
    if [[ "$trimmed" =~ ^[a-zA-Z0-9_-]+:\ *$ ]]; then
      group="${trimmed%%:*}"

      # Determine nesting depth
      if (( leading_spaces > indent )); then
        group_stack[$((indent+2))]=$current_group
      elif (( leading_spaces < indent )); then
        unset group_stack[$((indent+2))]
      fi

      indent=$leading_spaces

      if [[ "$line" == *"children:"* ]]; then
        current_group="$group"
      elif [[ "$line" == *"hosts:"* ]]; then
        current_group="$group"
        group_to_hosts["$current_group"]=""
      fi
    elif [[ "$trimmed" =~ ^[a-zA-Z0-9._-]+:\ *$ ]]; then
      host="${trimmed%%:*}"
      if [[ -n "$current_group" ]]; then
        group_to_hosts["$current_group"]+="$host "
      fi
    fi
  done < "$file"

  # Output groups that have hosts (even if added later)
  for grp in "${!group_to_hosts[@]}"; do
    echo "$grp"
  done
}

# Get hosts from a given group in the file (non-nested for now)
get_hosts_for_group() {
  local file="$1"
  local group="$2"

  awk "/^ *$group:/,/^[^ ]/" "$file" | grep -E '^\s{6}[a-zA-Z0-9._-]+:' | awk -F: '{print $1}' | sed 's/ *//g'
}

# Tab-complete options interactively
prompt_with_completion() {
  local prompt="$1"
  shift
  local options=("$@")
  local choice

  while true; do
    read -e -p "$prompt " choice
    for opt in "${options[@]}"; do
      if [[ "$choice" == "$opt" ]]; then
        echo "$choice"
        return
      fi
    done
    echo "Invalid choice. Try again: ${options[*]}"
  done
}

# Step 1: Select group
group_options=("PROD" "NONPROD")
selected_group=$(prompt_with_completion "Select environment group (PROD/NONPROD): " "${group_options[@]}")
[[ -z $selected_group ]] && echo "No group selected. Exiting." && exit 1

group_dir="${ENV_GROUPS[$selected_group]}"
env_list=$(find "$SERVER_DIR/$group_dir" -mindepth 1 -maxdepth 1 -type d -exec basename {} \;)
selected_env=$(prompt_with_completion "Select environment in $selected_group: " $env_list)
[[ -z $selected_env ]] && echo "No environment selected. Exiting." && exit 1

# Step 2: Load and parse YAML
inventory_file="$SERVER_DIR/$group_dir/$selected_env/hosts.yml"
[[ ! -f "$inventory_file" ]] && echo "File not found: $inventory_file" && exit 1

group_names=($(extract_groups_and_hosts "$inventory_file"))
selected_group_name=$(prompt_with_completion "Select group with hosts in $selected_env: " "${group_names[@]}")
[[ -z $selected_group_name ]] && echo "No group selected. Exiting." && exit 1

# Step 3: Host selection
host_names=($(get_hosts_for_group "$inventory_file" "$selected_group_name"))
[[ ${#host_names[@]} -eq 0 ]] && echo "No hosts found in group '$selected_group_name'" && exit 1

selected_host=$(prompt_with_completion "Select host in group '$selected_group_name': " "${host_names[@]}")
[[ -z $selected_host ]] && echo "No host selected. Exiting." && exit 1

# Step 4: Determine SSH user
if [[ "$selected_group" == "PROD" ]]; then
  ssh_user="${USER}.sad"
else
  ssh_user="${USER}.lsad"
fi

# Step 5: SSH connect
echo "Connecting to $selected_host as $ssh_user..."
ssh "${ssh_user}@${selected_host}"
