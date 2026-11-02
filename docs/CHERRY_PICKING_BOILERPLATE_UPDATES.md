# Pulling Individual Boilerplate Updates into a Copied Project

Use this guide when a project was created by **copying** the boilerplate (or
from a repository template) and therefore has its own, unrelated Git history,
for example a single "initial commit from boilerplate". You want a few specific
fixes from the boilerplate without a full re-sync.

Related guides:

- `USING_BOILERPLATE_AS_UPSTREAM.md`: projects cloned with boilerplate history
  (use `git merge`).
- `rsync-boilerplate.md`: large, one-off catch-up syncs.

## Why cherry-pick works without shared history

`git cherry-pick <commit>` replays one commit as a 3-way merge against that
commit's **own parent**. It never needs a common ancestor between the two
repositories, only that Git has the commit's objects locally. It keeps the
original message and author, and produces normal conflict markers if you have
edited the same lines.

It works best when your files were identical to the boilerplate at some point,
which is true right after a copy.

## Generic example

Placeholders used below:

- `<boilerplate>`: local path or URL of the boilerplate repo
  (e.g. `~/dev/common/greenfield-boilerplate`)
- `<baseline>`: the boilerplate commit your project was copied from
- `<sha1> <sha2>`: the boilerplate commits you want

### 1. Record your baseline (once)

Find the boilerplate commit whose file tree matches your project's initial
commit. If the hashes are equal, that is your baseline:

```bash
# in your project
git rev-parse <first-commit>^{tree}

# in the boilerplate
git rev-parse <candidate-commit>^{tree}
```

Write the baseline hash somewhere durable (this file, the README, or a git tag):

```bash
git tag boilerplate-baseline <first-commit>   # then note <baseline> in the tag message
```

After each update, move the note forward to the last boilerplate commit you
have taken.

### 2. Branch

```bash
git switch -c chore/boilerplate-update
```

Start from a clean working tree (`git status` should be empty).

### 3. Fetch the boilerplate

Either add a named remote (reusable):

```bash
git remote add boilerplate <boilerplate>
git fetch boilerplate
```

or fetch once without adding a remote:

```bash
git fetch <boilerplate> main     # commits are then reachable via FETCH_HEAD
```

### 4. See what is new

```bash
# commits after your baseline
git log --oneline <baseline>..boilerplate/main     # with a remote
git log --oneline <baseline>..FETCH_HEAD           # one-off fetch

# what a single commit touches
git show --stat <sha1>
```

### 5. Cherry-pick what you want

```bash
git cherry-pick <sha1> <sha2>          # specific commits, in order
git cherry-pick <baseline>..<sha2>     # a contiguous range (excludes <baseline>)
```

Add `-x` to append "(cherry picked from commit ...)" to each message. This makes
it easy to see later which boilerplate commits you already have.

If you want the changes **uncommitted** so you can combine or adjust them
first, use `-n`:

```bash
git cherry-pick -n <sha1> <sha2>
```

### 6. Resolve conflicts (if any)

```bash
git status                  # lists conflicted files
# edit files, remove <<<<<<< ======= >>>>>>> markers
git add <files>
git cherry-pick --continue  # or: git cherry-pick --abort
```

### 7. Check for things the patch could not know about

Boilerplate commits are written without knowing your application code, so look
for interactions:

- **Migrations:** run `python manage.py makemigrations --check --dry-run`. If
  your app also added migrations, check numbering and dependencies.
- **Model changes:** search your own code for assumptions the change breaks (for
  example, a field that became nullable and is used in a query or permission
  check).
- **Config and env:** compare `.env.example` changes against your real `.env`.

### 8. Test and merge

Run the backend and frontend test suites and start the app. Then merge the
branch into `main` as usual.

## Alternative: patch files

If you prefer not to add the boilerplate's objects to your repo, export and
apply a patch instead:

```bash
# in the boilerplate
git format-patch -N --stdout > /tmp/boilerplate-update.patch   # last N commits

# in your project
git apply --check /tmp/boilerplate-update.patch   # dry run
git apply /tmp/boilerplate-update.patch           # leaves changes uncommitted
# or: git am /tmp/boilerplate-update.patch        # applies as commits
```

`git apply` is all-or-nothing: if any hunk does not fit, nothing is changed.
`git cherry-pick` is more forgiving because it can leave conflict markers for
you to resolve.

## Rules of thumb

- Take boilerplate changes **on a branch**, never directly on `main`.
- Prefer small, targeted picks over big syncs. If you need many changes at once,
  see `rsync-boilerplate.md`.
- Do not push project work to the boilerplate remote by accident.
- Never take secrets, databases, `node_modules`, or build output from the
  boilerplate.
- Update your recorded baseline after each update.
