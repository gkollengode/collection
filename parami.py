import paramiko
import getpass
import os
import re
from rich import print
from rich.prompt import Prompt
from rich.panel import Panel

# === Prompt jumpbox credentials ===
jumpbox_host = Prompt.ask("Jumpbox hostname", default="jumpbox.example.com")
jumpbox_user = Prompt.ask("Jumpbox username")
base_password = getpass.getpass("Enter your password (excluding RSA): ")
rsa_token = Prompt.ask("Enter RSA token")
combined_password = f"{jumpbox_user}{base_password}{rsa_token}"

# === CyberArk CLI command to retrieve password ===
cyberark_command = (
    "/opt/CARKaim/sdk/clipasswordsdk GetPassword "
    "/p AppDescs.AppID=MyApp /p Query=Safe=MySafe;Object=MyAccount"
)

# === Interactive auth handler ===
def keyboard_handler(title, instructions, prompts):
    return [combined_password for _ in prompts]

# === Connect to jumpbox via Paramiko Transport ===
print(Panel(f"Connecting to [yellow]{jumpbox_host}[/] as [green]{jumpbox_user}[/]...", title="Jumpbox"))

transport = paramiko.Transport((jumpbox_host, 22))

try:
    transport.connect()
    transport.auth_interactive(jumpbox_user, keyboard_handler)
except paramiko.AuthenticationException:
    print("[red]❌ Authentication failed[/]")
    exit(1)

# === Use SSHClient to run command ===
jump_client = paramiko.SSHClient()
jump_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
jump_client._transport = transport

stdin, stdout, stderr = jump_client.exec_command(cyberark_command)
output = stdout.read().decode().strip()
error = stderr.read().decode().strip()

jump_client.close()

if error:
    print(f"[red]❌ CyberArk command failed:[/] {error}")
    exit(1)

match = re.search(r"Password\s*=\s*(.+)", output)
if not match:
    print("[red]❌ Could not parse CyberArk password[/]")
    exit(1)

cyberark_password = match.group(1).strip()
print("[green]✅ Retrieved CyberArk password[/]")

# === Write to env file ===
env_file_path = os.path.expanduser("~/.cyberark_env")
with open(env_file_path, "w") as f:
    f.write(f'export CYBERARK_PASSWORD="{cyberark_password}"\n')

print(Panel(f"[bold green]Saved password to:[/] {env_file_path}\n\n[bold]👉 Run this in your terminal:[/]\n\n[cyan]source ~/.cyberark_env[/]"))

