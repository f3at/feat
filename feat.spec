%global __python python

%{!?python_sitelib: %define python_sitelib %(%{__python} -c "from distutils.sysconfig import get_python_lib; print get_python_lib()")}
%{!?pyver: %define pyver %(%{__python} -c "import sys ; print sys.version[:3]")}
%define version 1.0.4
%define unmangled_version 1.0.4
%define build_rev 1

Name:           python-feat
Summary:        Flumotion Asynchronous Autonomous Agent Toolkit
Version:        %{version}
Release:        %{?build_rev}%{?dist}
Source0:        feat-%{unmangled_version}.tar.gz

Group:          Development/Languages
License:        GPL
URL:            http://www.flumotion.com

BuildRoot:      %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)

BuildRequires:  python-devel >= 2.6
BuildRequires:  python-setuptools >= 0.6c9

Requires:       python-twisted-core
Requires:       python-twisted-web
Requires:       nsca-client

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

# Install sbin scripts
install -m 755 -d $RPM_BUILD_ROOT%{_sbindir}
install -m 755 \
        sbin/feat-update-nagios \
        $RPM_BUILD_ROOT%{_sbindir}/feat-update-nagios

# Setup service script
install -d $RPM_BUILD_ROOT%{_sysconfdir}/rc.d/init.d
install -d $RPM_BUILD_ROOT%{_sysconfdir}/sysconfig
install -m 755 \
        conf/redhat/feat.init \
        $RPM_BUILD_ROOT%{_sysconfdir}/rc.d/init.d/feat
install -m 640 \
        conf/redhat/feat.sysconfig \
        $RPM_BUILD_ROOT%{_sysconfdir}/sysconfig/feat

# Create support directories
install -d $RPM_BUILD_ROOT%{_localstatedir}/lib/feat
install -d $RPM_BUILD_ROOT%{_localstatedir}/lock/feat
install -d $RPM_BUILD_ROOT%{_localstatedir}/log/feat
install -d $RPM_BUILD_ROOT%{_localstatedir}/run/feat


# Install default configuration file
install -m 644 conf/feat.ini $RPM_BUILD_ROOT%{_sysconfdir}/feat/feat.ini

# Install sudoers config
install -m 755 -d $RPM_BUILD_ROOT%{_sysconfdir}/sudoers.d
install -m 440 etc/sudoers.d/feat $RPM_BUILD_ROOT%{_sysconfdir}/sudoers.d/feat

# Install share files
%define _sharedir $RPM_BUILD_ROOT%{_datadir}/python-feat
install -m 755 -d %{_sharedir}/conf
install -m 755 -d %{_sharedir}/conf/postgres
install -m 755 -d %{_sharedir}/conf/redhat
install -m 755 -d %{_sharedir}/tools
install -m 755 -d %{_sharedir}/tools/PKI
install -m 755 -d %{_sharedir}/tools/PKI/bin
install -m 755 -d %{_sharedir}/tools/PKI/template
install -m 755 -d %{_sharedir}/gateway
install -m 755 -d %{_sharedir}/gateway/static
install -m 755 -d %{_sharedir}/gateway/static/images
install -m 755 -d %{_sharedir}/gateway/static/script
install -m 644 -t %{_sharedir}/gateway/static \
    gateway/static/feat.css \
    gateway/static/facebox.css
install -m 644 -t %{_sharedir}/gateway/static/images gateway/static/images/*
install -m 644 -t %{_sharedir}/gateway/static/script gateway/static/script/*

install -m 644 -t %{_sharedir}/conf \
  conf/authorized_keys \
  conf/client.p12 \
  conf/client_private_key.pem \
  conf/client_public_cert.pem \
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
  tools/start_rabbitctl.sh \
  tools/start_rabbit.sh \
  tools/web.py
install -m 644 -t %{_sharedir}/tools/PKI tools/PKI/feat.conf
install -m 644 -t %{_sharedir}/tools/PKI/bin tools/PKI/bin/*
install -m 644 -t %{_sharedir}/tools/PKI/template tools/PKI/template/*

# Install the logrotate entry
%{__install} -m 0644 -D doc/redhat/feat.logrotate \
    %{buildroot}%{_sysconfdir}/logrotate.d/feat

%clean
rm -rf $RPM_BUILD_ROOT


%pre
/usr/sbin/useradd -s /sbin/nologin -r -M feat > /dev/null 2> /dev/null || :

%preun
# if removal and not upgrade, stop the processes and clean up
if [ $1 -eq 0 ]
then
  /sbin/service feat stop > /dev/null

  rm -rf %{_localstatedir}/run/feat*

  /sbin/chkconfig --del feat
fi


%files
%defattr(-,root,root,-)

%doc README RELEASE LICENSE.GPL doc examples

%attr(664,root,feat) %config(noreplace) %{_sysconfdir}/feat/feat.ini
%config(noreplace) %{_sysconfdir}/sysconfig/feat
%config(noreplace) %{_sysconfdir}/logrotate.d/feat

%attr(775,root,feat) %{_sysconfdir}/feat
%attr(440,root,root) %config(noreplace) %{_sysconfdir}/sudoers.d/feat

%{_sysconfdir}/rc.d/init.d/feat

%{python_sitelib}/*
%{_bindir}/feat
%{_bindir}/feat-service
%{_bindir}/feat-couchpy
%{_bindir}/feat-dbload
%{_bindir}/feat-locate

%{_sbindir}/feat-update-nagios

%{_datadir}/python-feat/*

%attr(755,root,feat) %{_sysconfdir}/feat
%attr(775,root,feat) %{_localstatedir}/lib/feat
%attr(775,root,feat) %{_localstatedir}/lock/feat
%attr(775,root,feat) %{_localstatedir}/log/feat
%attr(775,root,feat) %{_localstatedir}/run/feat

%changelog
* Mon Sep 29 2014 Thomas Vander Stichele <thomas at apestaart dot org>
- 1.0.0-1
- time to flip the big major number

* Thu Aug 21 2014 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.29.8-2
- bugfix release for timeouts

* Tue Aug 19 2014 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.29.8-1
- new release

* Thu Jul 31 2014 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.29.7-1
- new release

* Thu Jul 10 2014 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.29.6-1
- new release

* Tue Jul 01 2014 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.29.5-2
- bug fixes after release

* Mon Jun 30 2014 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.29.5-1
- new release

* Wed Jun 11 2014 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.29.4-1
- new release

* Tue May 13 2014 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.29.3-1
- new release

* Tue Apr 29 2014 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.29.2-1
- new release

* Wed Apr 02 2014 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.29.1-2
- bug fix for alertclean

* Mon Mar 10 2014 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.29.0-1
- new release

* Tue Feb 04 2014 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.28.3-1
- new release

* Tue Jan 14 2014 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.28.2-1
- new release

* Tue Jan 07 2014 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.28.1-1
- new release

* Mon Dec 02 2013 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.28.0-1
- new release

* Fri Sep 27 2013 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.27.3
- new release, with DNS fix

* Fri Sep 13 2013 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.27.2
- new release

* Mon Aug 19 2013 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.27.1
- new release, optimize queries

* Wed Aug 14 2013 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.27.0
- new release

* Tue May 14 2013 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.25.2
- new release

* Wed May 08 2013 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.25.1
- new release including bugfix for multipart couchdb

* Tue May 07 2013 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.25.0-2
- bugfix to not require SSL client cert when having ca bundle

* Tue Apr 30 2013 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.25.0-1
- new release

* Tue Feb 19 2013 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.24.4-1
- new release

* Mon Feb 11 2013 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.24.3-1
- new release

* Thu Jan 17 2013 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.24.2-1
- new release

* Tue Jan 08 2013 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.24.1-1
- new release

* Wed Dec 19 2012 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.24.0-1
- new release

* Tue Dec 04 2012 Thomas Vander Stichele <thomas at apestaart dot org>
- Add logrotate script

* Tue Nov 20 2012 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.23.4-1
- new release

* Mon Nov 12 2012 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.23.3-1
- new release

* Thu Jun 28 2012 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.19.2-1
- new release

* Fri Jun 15 2012 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.19.1-2
- new release

* Thu May 10 2012 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.19.0-1
- add sudoers.d configuration
- add feat-update-nagios
- new release

* Sat Apr 07 2012 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.18.1-1
- new release

* Tue Mar 13 2012 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.18.0-0
- feat does not need to write in /etc/feat

* Wed Feb 29 2012 Thomas Vander Stichele <thomas at apestaart dot org>
- 0.16-2
- Create directories for sockets and locks

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
