# Course profiles

Course profiles are optional, reusable subject presets. Choose one in
**Home → Course Profile**, save, then Launch. A profile affects only remote
translation terminology and finalized-ASR corrections; Apple Draft remains the
zero-context fastest path.

Each profile is a folder with a generic, portable name:

```text
my-subject/
├── profile.json
├── glossary.tsv             # optional: English<TAB>Chinese
├── corrections.tsv          # optional: finalized ASR only, English<TAB>English
└── do_not_translate.txt     # optional: one protected technical term per line
```

`profile.json` requires a display name and a concise discipline background:

```json
{
  "name": "Statistical Machine Learning",
  "domain": "Statistical machine learning. Preserve standard terminology in probability, statistics, linear algebra, optimization, and machine learning."
}
```

The folder name is the saved ID. The display name must not depend on a local
university course code. Keep corrections conservative: they are applied only
to finalized English, but an overly broad replacement can still alter a valid
word. Personal lecture transcripts are intentionally not read or bundled.
