from docketeer_git.backup import backup

git_tasks = [backup]

task_collections = ["docketeer_git:git_tasks"]

__all__ = ["git_tasks", "task_collections"]
