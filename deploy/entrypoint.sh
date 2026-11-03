#!/bin/sh
# The pipeline's workspace is the `pipeline-data` volume (/workspace): pipeline.db, data/, work/,
# reports/, logs/. config/ and prompts/ come from the image, so an image update brings new ones;
# mount your own folder on /workspace/config to change them.
set -e
cd /workspace
mkdir -p data work reports logs secrets imports
for dir in config prompts; do
    if [ -L "$dir" ] || [ ! -e "$dir" ]; then
        ln -sfn "/app/$dir" "$dir"
    fi
done
exec "$@"
