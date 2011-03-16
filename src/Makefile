PYTHON = /usr/bin/python2.6
top_srcdir = .
COVERAGE_MODULES = feat
TOOLS = ../tools
TRIAL = ${TOOLS}/flumotion-trial
PEP8 = ${TOOLS}/pep8.py --repeat
SHOW_COVERAGE = ${TOOLS}/show-coverage.py

check-local: check-tests check-local-pep8

check-local-pep8:
	find $(top_srcdir) -name \*.py | grep -v extern | \
	sort -u | xargs $(PYTHON) $(PEP8)

check-tests:
	$(PYTHON) $(TRIAL) $(TRIAL_FLAGS) $(COVERAGE_MODULES)

check-tests-fast:
	@make check-tests \
	   TRIAL_FLAGS="--skip-slow"

coverage:
	@test ! -z "$(COVERAGE_MODULES)" ||				\
	(echo Define COVERAGE_MODULES in your Makefile; exit 1)
	rm -f feat-saved-coverage.pickle
	$(PYTHON) $(TRIAL) --temp-directory=_trial_coverage --coverage --saved-coverage=feat-saved-coverage.pickle $(COVERAGE_MODULES)
	make show-coverage

show-coverage:
	@test ! -z "$(COVERAGE_MODULES)" ||				\
	(echo Define COVERAGE_MODULES in your Makefile; exit 1)
	@keep="";							\
	for m in $(COVERAGE_MODULES); do				\
		echo adding $$m;					\
		keep="$$keep `ls _trial_coverage/coverage/$$m*`";	\
	done;								\
	$(PYTHON) $(SHOW_COVERAGE) $$keep

check-fast:
	@make check-commit \
	  TRIAL_FLAGS="--skip-slow"

check-commit:
	@current=`pwd`;							\
	repo=`dirname $$current`;					\
	reponame=`basename $$repo`;					\
	dst=/tmp/$$reponame;						\
	if test -d $$dst; then 						\
	(echo Removing old $$dst; rm -rf $$dst);			\
	fi;								\
	cd /tmp;							\
	git clone --recursive --depth 0 $$repo;                      	\
	cd $$reponame/src;						\
	make check-local;						\
	cd $$current;							\
	rm -rf $$dst;
