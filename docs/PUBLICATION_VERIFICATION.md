# Git publication and repository visibility

The repository browser and Git-data API reported an empty repository even while other endpoints reported published files. A direct branch link also failed for the owner. Earlier connector-only publication checks therefore did not establish browser visibility.

After the owner completed GitHub CLI device authentication, independent Git transport confirmed:

```
15c1ecb4dbbedcf98a3443a3e457e9aa19a1201a refs/heads/kube-remediation-demo
49155c691f8f3d7201721af3101a39ab4c516b0b refs/heads/main
```

An authenticated `git fetch --unshallow origin` successfully retrieved the complete history. The authenticated Contents API listed the project directories on the demo branch. Direct authenticated Actions API reads also confirmed benchmark run `38587061935` as failed and source CI run `38679786443` as successful at the previously recorded source commits.

Nevertheless, the Git-data reference endpoint continued to return HTTP 409, `Git Repository is empty.` The discrepancy is real; the branch was not missing from Git transport. Its underlying GitHub cause has not been established.

A normal Git push of this documentation is used to test whether a receive operation resolves the visibility state. No benchmark source, frozen plan, model result or default-branch contents are changed. Repository visibility must be checked separately from Git object identity and CI results.

Open the [project branch](https://github.com/tuanngocfun/agent/tree/kube-remediation-demo) and [benchmark report](https://github.com/tuanngocfun/agent/blob/kube-remediation-demo/reports/benchmark-v1-2026-10-14/README.md). The repository's default branch is `main`; the complete project is on `kube-remediation-demo`.
