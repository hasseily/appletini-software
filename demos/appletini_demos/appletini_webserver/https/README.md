# Appletini public HTTPS trust roots

Appletini F1.3.4 embeds these 29 roots and creates missing seed
pairs from an experimental XADC source. It needs no PEM or Python setup.
Use a writable SD card, menu/DHCP DNS and an RTC set to UTC. Existing seeds
remain in use; the XADC source still needs physical-board measurements.

An existing `ATNETCA.PEM` in the FAT SD-card root overrides F1.3.4's embedded
bundle. Remove the old file to use the embedded roots, or replace it with
this 29-root bundle, then reboot. The file belongs outside the ProDOS disk
image. Keep the board's seed files. This folder contains no seeds.

`roots.json` records the public root selection and its hashes. Keep it as
the receipt for this bundle. The 29-root PEM uses 37359 bytes and has SHA-256:

```text
8f305ef87b0fc03cb11f0f8ec2d3372c811940e52894f847d3bf4efd2c9cc94c
```

This selection includes the SSL.com TLS ECC Root CA 2022 needed by the
current example.com chain and the direct Go Daddy Root Certificate
Authority - G2 needed by archive.org. The previous 28 roots remain intact.
SHA-1 certificate signatures remain disabled. The source is the pinned Mozilla CA input in
Appletini firmware's `third_party/mozilla-ca/`. `LICENSE-roots.txt` contains
the MPL 2.0 notice. These files are ordinary copies of
`appletini-one/software/https_setup/ATNETCA.PEM` and `roots.json`, refreshed
on 2026-10-29. Browser builds read the local copies in this folder.

F1.3.4 also supports the 8192-byte HTTP header-line limit. The browser ZIP does not contain
firmware. Installing trust roots alone does not change that limit.
