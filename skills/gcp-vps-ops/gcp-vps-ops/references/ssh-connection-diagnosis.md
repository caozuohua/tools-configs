# SSH Connection Failure Diagnosis

When `gcloud compute ssh` or direct `ssh` to a VPS fails, follow this systematic diagnosis. Covers the 2026-06-27 incident where a non-GCP VPS (107.173.171.105, Hostwinds) became unreachable.

## Symptom Matrix

| Error | Meaning | Next Step |
|-------|---------|-----------|
| `Host key verification failed` | Server not in known_hosts | Run `ssh-keyscan <IP> >> ~/.ssh/known_hosts` |
| `Permission denied (publickey,password)` | Server accepts both but rejects yours | Key not registered OR wrong key |
| `Permission denied (publickey)` | Server rejects your key specifically | Try different key file |
| `Connection timed out` | Firewall or server down | Check from different network |
| `Connection refused` | SSH daemon not running on that port | Try different port, or server is dead |
| gcloud: `Must be a match of regex` | gcloud needs instance NAME, not IP | Use `--tunnel-through-iap` or find instance name |
| gcloud: `Could not fetch resource` | No permission to describe instance | Request `compute.instances.list` |

## Diagnosis Playbook

### Step 1: Verify basic connectivity
```bash
ping -c 2 <IP>  # Is the host alive?
nc -zv <IP> 22  # Is port 22 open?
```

### Step 2: Check SSH key acceptance
```bash
ssh -v -i ~/.ssh/id_ed25519 -o StrictHostKeyChecking=no -o ConnectTimeout=5 user@<IP> "echo ok" 2>&1 | grep -E "Offering|Authentication|debug1: Server accepts)"
```
Look for: `Server accepts publickey` → key auth is offered but rejected. Means the public key is NOT in the server's `authorized_keys`.

### Step 3: Try gcloud SSH with instance name (GCP instances, preferred)
```bash
gcloud compute ssh <INSTANCE_NAME> --zone=<ZONE> --command='hostname'
```
**Requires instance name** — IP addresses fail with `Must be a match of regex`. If you don't have the instance name:
```bash
# Try listing instances (requires compute.instances.list permission)
gcloud compute instances list --project=<PROJECT> --format="value(name,zone,networkInterfaces[0].accessConfigs[0].natIP)"
```

### Step 3b: gcloud SSH via public IP + --region + --network (no instance name needed)
When you lack `compute.instances.list` permission but know the instance's public IP, region, and VPC network:
```bash
gcloud compute ssh root@<PUBLIC_IP> --region=us-central1 --network=default \
  --project=<PROJECT> --zone=us-central1-a --ssh-key-file=~/.ssh/id_ed25519 \
  --command="hostname"
```
**gcloud CLI v473+ forces IAP tunnel for public IPs even with `--plain`**. The `--region + --network` approach bypasses both the instance-name requirement and IAP tunnel. If you get `not authorized` on IAP, you're forced back to needing the instance name.

### Step 4: Try gcloud IAP tunnel
```bash
gcloud compute ssh --tunnel-through-iap <INSTANCE_NAME> --zone=<ZONE> --command='hostname'
```
Also requires instance name, not IP.

### Step 5: sshpass fallback (when password is known)
```bash
# Install if needed
sudo apt-get install -y sshpass

# Use with explicit password
sshpass -p '<PASSWORD>' ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 user@<IP> "hostname"
```

### Step 6: Non-GCP VPS (Hostwinds / Vultr / DigitalOcean etc.)
For non-GCP VPS, gcloud SSH is not an option. Your options:
1. **Provide password** → use `sshpass`
2. **Add your public key** → log in via VPS control panel / web terminal, append to `~/.ssh/authorized_keys`
3. **Use VPS provider's web console** → most providers (Hostwinds, Vultr, DO) have browser-based SSH in their dashboard

## Common Key Rejection Patterns

### "id_ed25519 rejected but google_compute_engine accepted"
On GCP instances with OS Login, the metadata service manages keys. Local key files (`id_ed25519`, `id_rsa`) are NOT automatically accepted — only keys added via `gcloud compute ssh` or the console are in OS Login. Always try `google_compute_engine` first.

### "Both publickey and password rejected"
The user's key is not in `authorized_keys` AND you don't have the password. Resolution requires either:
- Access to the VPS provider's control panel to add your SSH key
- A password reset via the provider's dashboard
- Manual intervention by someone with access

## User Preference (2026-06-27)
When asked "how do you connect?", user immediately said "用gcloud ssh". This indicates gcloud SSH is the preferred method. However, 107.173.171.105 is a Hostwinds VPS (not GCP), so gcloud SSH is not applicable. Always clarify whether the VPS is GCP or external before attempting gcloud SSH.
