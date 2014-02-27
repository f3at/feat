PYTHON = python
top_srcdir = src
COVERAGE_MODULES = feat
TOOLS = tools
TRIAL = ${TOOLS}/flumotion-trial
PEP8 = ${TOOLS}/pep8.py --repeat
SHOW_COVERAGE = ${TOOLS}/show-coverage.py

check-local: check-tests check-local-pep8

check-local-pep8:
	find $(top_srcdir) -name \*.py | grep -v extern | \
	sort -u | xargs $(PYTHON) $(PEP8)

pyflakes:
	find $(top_srcdir) -name \*.py | grep -v extern | \
	sort -u | xargs pyflakes

pychecker:
	find $(top_srcdir) -name \*.py | grep -v extern | \
	sort -u | xargs pychecker

check-tests:
	$(PYTHON) $(TRIAL) $(TRIAL_FLAGS) $(COVERAGE_MODULES)

check-tests-fast:
	@make check-tests \
	   TRIAL_FLAGS="--skip-slow"

check-doc: doc/reference/html/index.html

doc/reference/html/index.html: Makefile src
	epydoc feat -o doc/reference/html -v --fail-on-warning | $(PYTHON) common/epyfilter.py common/efc.py

docs:
	@-rm doc/reference/html/index.html
	make doc/reference/html/index.html

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
	current=`pwd`;							\
        repo=`pwd`;							\
	reponame=`basename $$current`;					\
	dst=/tmp/$$reponame;						\
	if test -d $$dst; then						\
	(echo Removing old $$dst; rm -rf $$dst);			\
	fi;								\
	cd /tmp;							\
	git clone --recursive --depth 0 $$repo;				\
	cd $$reponame/src;						\
	make check-local;						\
	cd $$current;							\
	rm -rf $$dst;

targz:
	python setup.py sdist
	mv dist/feat-*.tar.gz .

rpm:    el6

el6:    targz
	mach -k -r c6l64 build feat.spec
