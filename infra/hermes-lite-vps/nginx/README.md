# nginx Routing Notes

Use nginx as the public HTTP/TLS entry point. Keep application ports on
loopback or blocked by the cloud firewall.

Expected public ports:

- `80/tcp`
- `443/tcp`

Expected private or blocked ports:

- `3000/tcp` for new-api
- `50404/tcp` for x-ui panel
- xray internal API ports such as `44301/tcp`

Always run:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

after installing or changing config.
