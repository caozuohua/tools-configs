# Remote Command Execution via gcloud compute ssh

## Running Python Remotely

When executing Python code through `gcloud compute ssh --command`, nested quotes cause bash parsing errors.

### ❌ Broken (nested single quotes)
```bash
gcloud compute ssh INSTANCE --zone=ZONE --command='python3 -c "print(\"hello\")"'
# bash: -c: line 1: syntax error near unexpected token `)'
```

### ✅ Fixed: Use single quotes for outer, double for inner
```bash
gcloud compute ssh INSTANCE --zone=ZONE --command='python3 -c "import json; print(json.dumps({\"ok\": true}))"'
```

### ✅ Fixed: Use heredoc-style for complex multi-line scripts
```bash
gcloud compute ssh INSTANCE --zone=ZONE --command='
python3 -c "
import json, sys, os
print(sys.version)
print(os.getcwd())
"
'
```

### ✅ Best for complex scripts: Upload then execute
```bash
# Upload
gcloud compute scp script.py INSTANCE:~/ --zone=ZONE

# Execute
gcloud compute ssh INSTANCE --zone=ZONE --command='python3 ~/script.py'
```

## Checking Remote System Resources

```bash
# Quick resource snapshot
gcloud compute ssh INSTANCE --zone=ZONE --command='top -bn1 | head -20 && echo --- && free -h && echo --- && df -h /'

# CPU count
gcloud compute ssh INSTANCE --zone=ZONE --command='nproc'

# OS version
gcloud compute ssh INSTANCE --zone=ZONE --command='cat /etc/os-release'
```

## Remote Python Environment Audit

```bash
gcloud compute ssh INSTANCE --zone=ZONE --command='python3 -c "
import importlib, subprocess, json

for lib in [\"requests\", \"flask\", \"numpy\", \"pandas\", \"httpx\", \"aiohttp\"]:
    try:
        importlib.import_module(lib)
        print(f\"{lib}: installed\")
    except ImportError:
        print(f\"{lib}: NOT installed\")

r = subprocess.run([\"pip3\", \"list\", \"--format=json\"], capture_output=True, text=True)
if r.returncode == 0:
    print(f\"Total pip packages: {len(json.loads(r.stdout))}\")
"'
```

## Notes

- Default user for `gcloud compute ssh` is the service account, not your personal user
- Home directory is `/home/sa_XXXXX`, not `/home/your-user`
- Write files to `/tmp/` or the service account's home directory to avoid permission issues
