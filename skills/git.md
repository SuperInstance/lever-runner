# Git Skill Pack — 40 Commands

```yaml
# Basic Operations
- intent: "show git status"
  command: "git status"
  tags: [git, status]

- intent: "stage all changes"
  command: "git add -A"
  tags: [git, stage]

- intent: "stage {{file}}"
  command: "git add {{file}}"
  tags: [git, stage, file]

- intent: "commit staged changes with message {{msg}}"
  command: "git commit -m \"{{msg}}\""
  tags: [git, commit]

- intent: "stage all and commit {{msg}}"
  command: "git add -A && git commit -m \"{{msg}}\""
  tags: [git, stage, commit]

- intent: "push to remote"
  command: "git push"
  tags: [git, push]

- intent: "push to {{remote}} {{branch}}"
  command: "git push {{remote}} {{branch}}"
  tags: [git, push, remote]

- intent: "pull latest changes"
  command: "git pull"
  tags: [git, pull]

- intent: "pull and rebase"
  command: "git pull --rebase"
  tags: [git, pull, rebase]

- intent: "clone repository {{url}}"
  command: "git clone {{url}}"
  tags: [git, clone]

- intent: "clone repository into {{dir}}"
  command: "git clone {{url}} {{dir}}"
  tags: [git, clone]

- intent: "fetch from remote"
  command: "git fetch --all"
  tags: [git, fetch]

- intent: "show git log"
  command: "git log --oneline -20"
  tags: [git, log]

- intent: "show detailed git log"
  command: "git log --oneline --graph --decorate -20"
  tags: [git, log, graph]

- intent: "show git log for {{file}}"
  command: "git log --oneline -- {{file}}"
  tags: [git, log, file]

- intent: "undo last commit keep changes"
  command: "git reset --soft HEAD~1"
  tags: [git, undo, commit]

- intent: "undo last commit discard changes"
  command: "git reset --hard HEAD~1"
  tags: [git, undo, commit, discard]

- intent: "discard uncommitted changes in {{file}}"
  command: "git checkout -- {{file}}"
  tags: [git, discard, file]

# Branching
- intent: "list branches"
  command: "git branch -a"
  tags: [git, branch, list]

- intent: "create branch {{name}}"
  command: "git branch {{name}}"
  tags: [git, branch, create]

- intent: "switch to branch {{name}}"
  command: "git checkout {{name}}"
  tags: [git, branch, switch]

- intent: "create and switch to branch {{name}}"
  command: "git checkout -b {{name}}"
  tags: [git, branch, create, switch]

- intent: "merge branch {{name}} into current"
  command: "git merge {{name}}"
  tags: [git, merge]

- intent: "rebase current branch onto {{branch}}"
  command: "git rebase {{branch}}"
  tags: [git, rebase]

- intent: "abort rebase"
  command: "git rebase --abort"
  tags: [git, rebase, abort]

- intent: "continue rebase"
  command: "git rebase --continue"
  tags: [git, rebase, continue]

- intent: "cherry pick commit {{hash}}"
  command: "git cherry-pick {{hash}}"
  tags: [git, cherry-pick]

- intent: "delete branch {{name}}"
  command: "git branch -d {{name}}"
  tags: [git, branch, delete]

- intent: "delete remote branch {{name}}"
  command: "git push origin --delete {{name}}"
  tags: [git, branch, delete, remote]

# Investigation
- intent: "show diff of staged changes"
  command: "git diff --cached"
  tags: [git, diff, staged]

- intent: "show diff of unstaged changes"
  command: "git diff"
  tags: [git, diff]

- intent: "show diff of {{file}}"
  command: "git diff {{file}}"
  tags: [git, diff, file]

- intent: "show diff between {{a}} and {{b}}"
  command: "git diff {{a}}..{{b}}"
  tags: [git, diff, compare]

- intent: "show who changed {{file}}"
  command: "git blame {{file}}"
  tags: [git, blame]

- intent: "show commit details {{hash}}"
  command: "git show {{hash}}"
  tags: [git, show, commit]

- intent: "show reflog"
  command: "git reflog -20"
  tags: [git, reflog]

- intent: "stash current changes"
  command: "git stash push -m \"{{msg}}\""
  tags: [git, stash]

- intent: "list stashes"
  command: "git stash list"
  tags: [git, stash, list]

- intent: "apply latest stash"
  command: "git stash pop"
  tags: [git, stash, apply]

- intent: "apply stash {{n}}"
  command: "git stash apply stash@{{{n}}}"
  tags: [git, stash, apply]

# Advanced
- intent: "find commit that introduced bug"
  command: "git bisect start"
  tags: [git, bisect]

- intent: "mark current commit as bad"
  command: "git bisect bad"
  tags: [git, bisect, bad]

- intent: "mark {{commit}} as good"
  command: "git bisect good {{commit}}"
  tags: [git, bisect, good]

- intent: "add submodule {{url}}"
  command: "git submodule add {{url}} {{path}}"
  tags: [git, submodule, add]

- intent: "initialize submodules"
  command: "git submodule update --init --recursive"
  tags: [git, submodule, init]

- intent: "add worktree {{branch}}"
  command: "git worktree add {{path}} {{branch}}"
  tags: [git, worktree, add]

- intent: "list worktrees"
  command: "git worktree list"
  tags: [git, worktree, list]

- intent: "show git tags"
  command: "git tag -l"
  tags: [git, tag, list]

- intent: "create tag {{name}}"
  command: "git tag -a {{name}} -m \"{{msg}}\""
  tags: [git, tag, create]

- intent: "show short statistics"
  command: "git shortlog -sn"
  tags: [git, stats, contributors]
```
