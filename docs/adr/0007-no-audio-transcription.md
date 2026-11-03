# No audio transcription; link-only stubs instead

The pipeline does not transcribe audio, locally (Whisper) or in the cloud. Text comes from the caption/description, the pinned comment, the linked website and existing subtitles (ticket 34). A caption that lists only ingredients, or ingredients plus a link, is a valid source and becomes a recipe with no steps. A Video that `classify` keeps but that has no usable text becomes a **link-only stub** in Mealie: name, thumbnail, source link and tags, plus the tag `link-only`. Nothing upgrades a stub automatically.

Why: the GPU setup and benchmark cost more than they return, and a saved video that is missing from Mealie is worse than a thin entry the user can open from the link.
