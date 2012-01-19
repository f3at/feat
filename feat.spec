%global __python python2.6
%{!?python_sitelib: %define python_sitelib %(%{__python} -c "from distutils.sysconfig import get_python_lib; print get_python_lib()")}
%{!?pyver: %define pyver %(%{__python} -c "import sys ; print sys.version[:3]")}
%define version 0.16
%define unmangled_version 0.16
%define build_rev 0

Name:           python-feat
Summary:        Flumotion Asynchronous Autonomous Agent Toolkit
Version:        %{version}
Release:        %{?build_rev}%{?dist}
Source0:        feat-%{unmangled_version}.tar.gz

Group:          Development/Languages
License:        Propietary
URL:            http://flumotion.com

BuildRoot:      %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)

BuildRequires:  python-devel >= 2.6
BuildRequires:  python-setuptools >= 0.6c9

Requires:       python-twisted-core
Requires:       python-twisted-web
Requires:       python-paisley >= 0.3.1-feat.1

Provides:       %{name}

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

# Create config directory
mkdir -p $RPM_BUILD_ROOT%{_sysconfdir}/feat

# Setup service script
install -d $RPM_BUILD_ROOT%{_sysconfdir}/rc.d/init.d
install -m 755 \
        conf/redhat/feat \
        $RPM_BUILD_ROOT%{_sysconfdir}/rc.d/init.d

# Create log and run directory
install -d $RPM_BUILD_ROOT%{_localstatedir}/log/feat
install -d $RPM_BUILD_ROOT%{_localstatedir}/run/feat

# Creates feat user home directory
install -d $RPM_BUILD_ROOT%{_localstatedir}/cache/feat

# Install default configuration file
install -m 644  conf/feat.ini $RPM_BUILD_ROOT%{_sysconfdir}/feat/feat.ini

# Install share files
%define _sharedir $RPM_BUILD_ROOT%{_datadir}/python-feat
install -m 755 -d %{_sharedir}/conf
install -m 755 -d %{_sharedir}/conf/postgres
install -m 755 -d %{_sharedir}/conf/redhat
install -m 755 -d %{_sharedir}/tools
install -m 755 -d %{_sharedir}/tools/PKI
install -m 755 -d %{_sharedir}/tools/PKI/bin
install -m 755 -d %{_sharedir}/tools/PKI/template
install -m 644 -t %{_sharedir}/conf \
  conf/authorized_keys \
  conf/dummy.p12 \
  conf/dummy_private_key.pem \
  conf/dummy_public_cert.pem \
  conf/feat.ini \
  conf/gateway.p12 \
  conf/gateway_ca.pem \
  conf/private.key \
  conf/public.key \
  conf/tunneling.p12
install -m 644 -t %{_sharedir}/conf/postgres conf/postgres/*
install -m 644 -t %{_sharedir}/conf/redhat conf/redhat/*
install -m 644 -t %{_sharedir}/tools \
  tools/configure_test_postgres.sh \
  tools/env \
  tools/flumotion-trial \
  tools/pep8.py \
  tools/show-coverage.py \
  tools/start_couch.sh \
  tools/start_feat.sh \
  tools/start_rabbitctl.sh \
  tools/start_rabbit.sh \
  tools/stop_feat.sh \
  tools/web.py
install -m 644 -t %{_sharedir}/tools/PKI tools/PKI/feat.conf
install -m 644 -t %{_sharedir}/tools/PKI/bin tools/PKI/bin/*
install -m 644 -t %{_sharedir}/tools/PKI/template tools/PKI/template/*


%clean
rm -rf $RPM_BUILD_ROOT


%pre
/usr/sbin/useradd -s /sbin/nologin \
        -r -d %{_localstatedir}/cache/feat -M \
        feat > /dev/null 2> /dev/null || :
/usr/sbin/usermod -d %{_localstatedir}/cache/feat \
        feat > /dev/null 2> /dev/null || :


%preun
# if removal and not upgrade, stop the processes and clean up
if [ $1 -eq 0 ]
then
  /sbin/service feat stop > /dev/null

  rm -rf %{_localstatedir}/run/feat*

  # clean out the cache/home dir too, without deleting it or the user
  rm -rf %{_localstatedir}/cache/feat/*
  rm -rf %{_localstatedir}/cache/feat/.[^.]*

  /sbin/chkconfig --del feat
fi


%files
%defattr(-,root,root,-)

%doc README RELEASE LICENSE.GPL doc examples

%config(noreplace) %{_sysconfdir}/feat/feat.ini
%attr(775, root, feat) %{_sysconfdir}/feat
%attr(664, root, feat) %{_sysconfdir}/feat/feat.ini

%{_sysconfdir}/rc.d/init.d/feat

%{python_sitelib}/*
%{_bindir}/feat
%{_bindir}/feat-couchpy
%{_bindir}/feat-dbload
%{_bindir}/feat-locate
%{_bindir}/feat-service

%{_datadir}/python-feat/*

%attr(775,root,feat) %{_sysconfdir}/feat
%attr(775,root,feat) %{_localstatedir}/run/feat
%attr(775,root,feat) %{_localstatedir}/log/feat
%attr(770,feat,feat) %{_localstatedir}/cache/feat


%changelog
* Mon Jan 16 2012 Sebastien Merle <s.merle@gmail.com>
- 0.16-1
- Updated the spec file to reflect setuptools changes.
- Added user feat creation.

* Mon Jan 16 2012 Sebastien Merle <s.merle@gmail.com>
- Bumped to 0.16

* Tue Dec 11 2011 Sebastien Merle <s.merle@gmail.com>
- 0.15
- FEAT Pre-Release 0.15

* Tue Oct 11 2011 Sebastien Merle <s.merle@gmail.com>
- 0.10.5
- FEAT Release 0.10.5.

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

