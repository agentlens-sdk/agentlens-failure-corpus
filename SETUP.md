# Host setup

Everything in BUILD.md that needs a human, a secret, or a browser. Do these in order; the corpus
does not run correctly until step 3.

## 1. Guardrail first (BUILD.md step 9)

In the Anthropic Console, set the **workspace spend limit equal to your credit balance**. This is
the cap you do not control at runtime. The ledger in `corpus/ledger.py` is the second cap, and
`budget.total_cap_usd` in `config.yaml` (currently $1950) is the third. Do this before the key
exists on the box, not after.

## 2. API key

    printf 'export ANTHROPIC_API_KEY=sk-ant-...\n' > ~/.corpus.env
    chmod 600 ~/.corpus.env

Never put the key in the repo. `corpus/redact.py` scrubs `sk-ant-*`, `ghp_*`, `gho_*` and `hf_*`
out of every trace and span before anything is written or pushed, but do not rely on that.

## 3. Remote + Pages (BUILD.md step 8)

    git remote add origin git@github.com:agentlens-sdk/agentlens-failure-corpus.git
    git push -u origin main

Deploy key with **write** access (the box pushes every night, unattended):

    ssh-keygen -t ed25519 -C corpus-box -f ~/.ssh/corpus_deploy -N ''
    cat ~/.ssh/corpus_deploy.pub     # paste into repo Settings > Deploy keys, tick "Allow write access"
    cat >> ~/.ssh/config <<'EOF'
    Host github.com-corpus
      HostName github.com
      User git
      IdentityFile ~/.ssh/corpus_deploy
      IdentitiesOnly yes
    EOF
    git remote set-url origin git@github.com-corpus:agentlens-sdk/agentlens-failure-corpus.git

Identity for the unattended commits:

    git config user.name  "corpus box"
    git config user.email "corpus@agentlens-sdk.github.io"

Pages: repo Settings > Pages > Source "Deploy from a branch", branch `main`, folder **`/site`**.
The dashboard fetches `stats.json` from its own directory, so it only renders once a nightly run
has committed `site/stats.json`.

Verify before walking away:

    python -c "from corpus import publisher; publisher.write_stats(); print(publisher.git_push('setup check'))"

That must print `True` and the commit must appear on GitHub.

## 4. Hugging Face (optional)

    pip install huggingface_hub && huggingface-cli login
    # then in config.yaml:
    publish:
      hf_dataset: "agentlens-sdk/agentlens-failure-corpus"

Blank `hf_dataset` skips the weekly parquet snapshot entirely. The git push is the primary channel;
HF is a convenience.

## 5. Cron (BUILD.md step 10)

    crontab -e
    # 02:00 nightly
    0 2 * * * . ~/.corpus.env && /path/to/agentlens-failure-corpus/run_nightly.sh

Check it took: `crontab -l`.

**macOS caveats**, if this laptop is the box:
- cron needs Full Disk Access (System Settings > Privacy & Security > Full Disk Access > add
  `/usr/sbin/cron`), or it cannot read files under `~/Downloads`.
- A sleeping Mac runs nothing. `sudo pmset repeat wakeorpoweron MTWRFSU 01:55:00`, and keep it
  plugged in. A `launchd` agent with `StartCalendarInterval` wakes the machine and cron does not;
  if nights start going missing, that is why.
- If the box is Linux instead: set Docker to start on boot only if you later enable the SWE-bench
  family, and put it on a UPS if it is at home.

`run_nightly.sh` is safe to run by hand at any time. It takes a lock, so a manual run and a cron
run cannot overlap.

## 6. What stops it

A `STOPPED` file in the repo root. Written by: total cap reached, 3 consecutive zero-trace nights,
3 consecutive failed-push nights, or a billing/auth error. Delete the file to resume. Nothing else
resumes automatically, on purpose.

Deleting `STOPPED` without reading it first defeats the point — the file names the reason.
