# Security Policy

## Reporting a vulnerability

Please report security issues **privately** via GitHub's **"Report a vulnerability"**
button on the repository's *Security* tab (Security Advisories) — not a public issue.

refscan is a local command-line tool. It makes outbound HTTPS requests to public
scholarly APIs (arXiv, Semantic Scholar, OpenAlex, Crossref, Unpaywall), reads and
writes files under the paper directory, and runs `pdftotext` as a subprocess. It has
no server, authentication, or remote-code-execution surface. The most relevant
concerns are around file handling (e.g. reference paths) and parsing untrusted
`.bib` / PDF input.

## Supported versions

The latest released version is supported; fixes ship in a new release.

## Response

This is a small project maintained on a best-effort basis — expect an initial reply
within a couple of weeks.
