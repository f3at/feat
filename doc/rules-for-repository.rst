Rules for using the git repository in *feat*, *flt* and *flumotion-flt* projects
================================================================================

People working on FLT need to be working against stable release of FEAT.

1. On the first day of the sprint we create a branch named cycle-<number>: ::

	git checkout -b cycle-1

2. The development is done on this branch, or private feature branches (and **rebased** do cycle branch).

3. At the end of the sprint cycle branch is **rebased** on top of master and then **merged** to it (it will be resolved as fast-forward with a merge commit). Then we **create signed a tag** named: release-<number>, which points to the merge commit. ::

       # update master branch
       git checkout master
       git pull --rebase
       # rebase cycle on top of master
       git checkout cycle-1
       git rebase origin/master
       # now merge it
       git checkout master
       git merge --no-ff cycle-1
       git tag -s release-1
       git push --tags


4. Hotfixes are done on cycle branches and cherry-picked to master. ::

	git checkout cycle-1
	git commit -am "Hotfix"
	git checkout master
	git cherry-pick cycle-1

5. For a feature to be delivered and consequently merged into master it has be done. **Definition of done:**

- Tests are passing,

- Tests exist,

- Code is merged to cycle branch,

- Buildbot is green,

- Code review has been approved.
