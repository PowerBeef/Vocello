# Vocello Website

This directory contains the public Vocello marketing site. It is a React + Vite app maintained inside the QwenVoice repo and deployed by Vercel with `website/` as the project root.

## Commands

Run these from the QwenVoice repo root:

```sh
npm --prefix website ci
npm --prefix website run dev
npm --prefix website run lint
npm --prefix website test
npm --prefix website run build
npm --prefix website run check
npm --prefix website run preview
```

When working from this directory, the same commands can be run without `--prefix website`.

## Deployment

Vercel should be configured with:

- Repository: `PowerBeef/Vocello`
- Root directory: `website`
- Install command: `npm ci`
- Build command: `npm run build`
- Output directory: `dist`

The former `PowerBeef/vocello-website` repository is historical after this migration.

Pull requests run the deterministic website contract and production build in the repository CI.
The checks use the exact Node/npm identities recorded in `config/toolchain.json`; browser inspection
is an additional visual review, not the only correctness signal.
