PYTHON = /usr/bin/python2.6
top_srcdir = .
COVERAGE_MODULES = feat flt
TOOLS = ../tools
TRIAL = ${TOOLS}/flumotion-trial
PEP8 = ${TOOLS}/pep8.py --repeat
SHOW_COVERAGE = ${TOOLS}/show-coverage.py

check-local: check-local-pep8

check-local-pep8:
	find $(top_srcdir) -name \*.py | sort -u | xargs $(PYTHON) $(PEP8)

coverage:
	@test ! -z "$(COVERAGE_MODULES)" ||				\
	(echo Define COVERAGE_MODULES in your Makefile; exit 1)
	rm -f feat-saved-coverage.pickle
	@$(PYTHON) $(TRIAL) --temp-directory=_trial_coverage --coverage --saved-coverage=feat-saved-coverage.pickle $(COVERAGE_MODULES)
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

