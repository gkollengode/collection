#!/bin/bash

SERVER_DIR="./servers"

# Mapping of environments to implicit groups
declare -A ENV_GROUPS=(
  [PRDA]="PROD"
  [PRDW]="PROD"
  [UNIT]="NONPROD"
  [INTG]="NONPROD"
  [PERF]="NONPROD"
  [QUAL]="NONPROD"
  [TRNG]="NONPROD"
)

# Recursively extract all groups that contain hosts
extract_groups_with_hosts() {
  local file="$1"
  awk '
    /^[a-zA-Z0-9_-]+:$/ { g=$1; next }
    /^\s{2,}[a-zA-Z0-9._-]+:$/ { if (g) groups[g]=1 }
    END { for (k in groups) print k }
  ' "$file"
}

# Get hosts under specific group (1 level)
get_hosts_for_group() {
  local file="$1"
  local group="$2"
  awk "/^ *$group:/,/^[^ ]/" "$file" | grep -E '^\s{4,}[a-zA-Z0-9._-]+:' | awk -F: '{print $1}' | sed 's/ *//g'
}

# Interactive prompt with completion
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
    echo "Invalid choice. Options: ${options[*]}"
  done
}

# Step 1: Select environment (based on folder names)
env_list=$(find "$SERVER_DIR" -mindepth 1 -maxdepth 1 -type d -exec basename {} \;)
selected_env=$(prompt_with_completion "Select environment (PRDA, UNIT, etc): " $env_list)
[[ -z $selected_env ]] && echo "No environment selected. Exiting." && exit 1

group_type="${ENV_GROUPS[$selected_env]}"
[[ -z "$group_type" ]] && echo "Unknown group type for $selected_env. Exiting." && exit 1

# Step 2: Load hosts.yml
inventory_file="$SERVER_DIR/$selected_env/hosts.yml"
[[ ! -f "$inventory_file" ]] && echo "File not found: $inventory_file" && exit 1

# Step 3: List groups with hosts
group_names=($(extract_groups_with_hosts "$inventory_file"))
selected_group=$(prompt_with_completion "Select group in $selected_env: " "${group_names[@]}")
[[ -z "$selected_group" ]] && echo "No group selected. Exiting." && exit 1

# Step 4: Host selection
host_names=($(get_hosts_for_group "$inventory_file" "$selected_group"))
selected_host=$(prompt_with_completion "Select host in group $selected_group: " "${host_names[@]}")
[[ -z "$selected_host" ]] && echo "No host selected. Exiting." && exit 1

# Step 5: Username logic
if [[ "$group_type" == "PROD" ]]; then
  ssh_user="${USER}.sad"
else
  ssh_user="${USER}.lsad"
fi

# Step 6: SSH connect
echo "Connecting to $selected_host as $ssh_user..."
ssh "${ssh_user}@${selected_host}"
