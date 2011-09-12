%global __python python2.6
%{!?python_sitelib: %define python_sitelib %(%{__python} -c "from distutils.sysconfig import get_python_lib; print get_python_lib()")}
%{!?pyver: %define pyver %(%{__python} -c "import sys ; print sys.version[:3]")}
%define version 0.1.2
%define unmangled_version 0.1.2
%define build_rev 0

Name:           python-featspec
Summary:        Feat example application
Version: 	%{version}
Release: 	%{?build_rev}%{?dist}
Source0: 	featchat-%{unmangled_version}.tar.gz

Group:          Development/Languages
License:        Propietary
URL:            http://flumotion.com

BuildRoot:      %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)

BuildRequires:  python-devel
BuildRequires:  python-setuptools >= 0.6c9
Requires:	python-simplejson
Requires:       python-feat
Requires:	python-twisted-core
Requires:	python-twisted-web

Provides:	%{name}

%description
Feat example application,

%prep
%setup -q -n featchat-%{unmangled_version}

%build
CFLAGS="$RPM_OPT_FLAGS" %{__python} setup.py build

%install
rm -rf $RPM_BUILD_ROOT
%{__python} setup.py install --skip-build --root=$RPM_BUILD_ROOT \
     --record=INSTALLED_FILES

install -m 644  \
        conf/featchat.ini \
              $RPM_BUILD_ROOT%{_sysconfdir}/feat/featchat.ini

%files
%defattr(-,root,root,-)
%{python_sitelib}/*
%_usr/bin/*


%clean
rm -rf $RPM_BUILD_ROOT
