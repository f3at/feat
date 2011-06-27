%global __python python2.6
%{!?python_sitelib: %define python_sitelib %(%{__python} -c "from distutils.sysconfig import get_python_lib; print get_python_lib()")}
%{!?pyver: %define pyver %(%{__python} -c "import sys ; print sys.version[:3]")}
%define version 0.1.2
%define unmangled_version 0.1.2
%define build_rev 0

Name:           python-feat
Summary:        Flumotion Asynchronous Autonomous Agent Toolkit
Version: 	%{version}
Release: 	%{?build_rev}%{?dist}
Source0: 	feat-%{unmangled_version}.tar.gz

Group:          Development/Languages
License:        Propietary
URL:            http://flumotion.com

BuildRoot:      %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)

BuildRequires:  python-devel
BuildRequires:  python-setuptools >= 0.6c9
Requires:	python-simplejson
Requires:	python-twisted-core
Requires:	python-twisted-web
#Requires:	couchdb >= 0.10
#Requires:	python-txamqp >= 0.3
#Requires:	amqp
#Requires:	rabbitmq-server >= 2.0
Provides:	%{name}

%description
Flumotion Asynchronous Autonomous Agent Toolkit

%prep
%setup -q -n feat-%{unmangled_version}

%build
CFLAGS="$RPM_OPT_FLAGS" %{__python} setup.py build

%install
rm -rf $RPM_BUILD_ROOT
%{__python} setup.py install --skip-build --root=$RPM_BUILD_ROOT --record=INSTALLED_FILES
%{__mv} $RPM_BUILD_ROOT/%_usr/bin/host.py $RPM_BUILD_ROOT/%_usr/bin/feat-host
%{__mv} $RPM_BUILD_ROOT/%_usr/bin/standalone.py $RPM_BUILD_ROOT/%_usr/bin/feat-standalone

%files
%defattr(-,root,root,-)
%{python_sitelib}/*
%_usr/bin/*

%clean
rm -rf $RPM_BUILD_ROOT

%changelog
* Fri Apr 1 2011 Sebastien Merle <sebastien@flumotion.com>
- 0.1.2-1
- Update for new release.

* Wed Mar 16 2010 Xavier Queralt Mateu <xqueralt@flumotion.com>
- 0.1.1-2
- Add dependencies

* Thu Mar 3 2010 Josep Joan Ribas <jribas@flumotion.com>
- 0.1.1-1
- Initial version for RHEL6.

