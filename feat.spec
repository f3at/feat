%global __python python2.6
%{!?python_sitelib: %define python_sitelib %(%{__python} -c "from distutils.sysconfig import get_python_lib; print get_python_lib()")}
%{!?pyver: %define pyver %(%{__python} -c "import sys ; print sys.version[:3]")}
%define version 0.10
%define unmangled_version 0.10
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
%{__python} setup.py install --skip-build --root=$RPM_BUILD_ROOT \
     --record=INSTALLED_FILES

install -m 644 src/feat/agencies/net/amqp0-8.xml \
     $RPM_BUILD_ROOT%{python_sitelib}/feat/agencies/net/amqp0-8.xml

# create config dir
install -d $RPM_BUILD_ROOT%{_sysconfdir}/feat
install -m 644  \
        conf/feat.ini \
              $RPM_BUILD_ROOT%{_sysconfdir}/feat/feat.ini
install -m 644  \
        conf/public.key \
              $RPM_BUILD_ROOT%{_sysconfdir}/feat/public.key
install -m 644  \
        conf/private.key \
              $RPM_BUILD_ROOT%{_sysconfdir}/feat/private.key
install -m 644  \
        conf/authorized_keys \
              $RPM_BUILD_ROOT%{_sysconfdir}/feat/authorized_keys

install -d $RPM_BUILD_ROOT%{_sysconfdir}/rc.d/init.d
install -m 755 \
        conf/redhat/feat \
	        $RPM_BUILD_ROOT%{_sysconfdir}/rc.d/init.d

# create log and run and cache and lib rrd directory
install -d $RPM_BUILD_ROOT%{_localstatedir}/log/feat
install -d $RPM_BUILD_ROOT%{_localstatedir}/run/feat

%files
%defattr(-,root,root,-)
%{python_sitelib}/*
%_usr/bin/*
%{_sysconfdir}/rc.d/init.d/feat
%attr(775,root,flumotion) %{_sysconfdir}/feat
%attr(775,root,flumotion) %{_localstatedir}/run/feat
%attr(775,root,flumotion) %{_localstatedir}/log/feat

%clean
rm -rf $RPM_BUILD_ROOT

%changelog
* Wed Sep 21 2011 Marek Kowalski <mkowalski@flumotion.com>
- 0.10
- Bump package version.

* Mon Aug 29 2011 Marek Kowalski <mkowalski@flumotion.com>
- 0.1.2-5
- Add service scripts

* Thu Jul 28 2011 Marek Kowalski <mkowalski@flumotion.com>
- 0.1.2-4
- Remove obsolete executable scripts

* Wed May 11 2011 Xavier Queralt <xqueralt@flumotion.com>
- 0.1.2-3
- Add missing amqp0-8.xml file into the package

* Fri Apr 1 2011 Sebastien Merle <sebastien@flumotion.com>
- 0.1.2-1
- Update for new release.

* Wed Mar 16 2010 Xavier Queralt Mateu <xqueralt@flumotion.com>
- 0.1.1-2
- Add dependencies

* Thu Mar 3 2010 Josep Joan Ribas <jribas@flumotion.com>
- 0.1.1-1
- Initial version for RHEL6.

