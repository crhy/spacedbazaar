# Changelog

## Unreleased

- The catalog tool can now fetch a catalogued release asset through an opted-in
  peer mirror (`--peer-mirror NAME=URL`): peers may supply bytes, the signed
  catalog still supplies authority, every candidate must match the origin-published
  size and SHA-256 before it is kept, rejections are recorded and the signed origin
  is always tried last, and the shipped catalog keeps `policy.peer_fetch: "off"`
  with `"peers": []` so today's installs are unchanged.
