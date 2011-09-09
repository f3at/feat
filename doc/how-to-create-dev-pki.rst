===================
How to create a PKI
===================

**WARNING**:

	This is describing a quick, simple and **UNSAFE** way of creating a PKI.
	this is good for development purpose but a proper PKI infrastructure should
	be use for production.

The Quick and Lazy Way
======================

To create new CA and certificates from scratch assuming the current directory
is the root of Feat checkout::

	cd tools/PKI
	bin/create_root_ca
	bin/create_issuing_ca tunneling
	bin/issue_cert tunneling tunneling ssl_server *.flumotion.fluendo.lan
	bin/create_issuing_ca gateway
	bin/issue_cert gateway gateway ssl_server *.flumotion.fluendo.lan
	bin/issue_cert gateway dummy ssl_client Name Surname email@address.lan

Then the generated files can be found there:

 - Tunneling Server PKCS12: ./tunneling_ca/certs/tunneling.p12
 - Gateway Server PKCS12: ./gateway_ca/certs/gateway.p12
 - Gateway Dummy Client PKCS12: ./gateway_ca/certs/dummy.p12


PKI and Feat
============

Feat needs keys and certificates for securing the gateway and the
tunneling backend. Both are using SSL and verify the other side certificate
has been issued by there own CA.

In practice it mean that Feat needs two CA or sub-CA, one for the gateway
and one for tunneling. This is required to prevent user with valid gateway
certificate to be able to push random message through a tunnel.

To facilitate maintenance, Feat is using PKCS12 format. This format allows
to store the private key, the certificate and the CA certification chain
all in only one file.

In theory, each feat service should have there own PKCS12 for gateway and
tunneling but for development we could use the same for all services.

To be able to connect to the gateway using a web browser, one should import
a PKCS12 issued but the gateway CA and set the gateway CA as trusted.

To prevent the browser to ask for confirmation every time it connect to
a gateway server with different hostname, one should generate a gateway
certificate with a common name matching there hostname. The default one
use *.flumotion.fluendo.lan, so when the CA is marked as trusted all
services hosted on any sub-domain of flumotion.fluendo.lan will do not
ask for confirmation.


Creating the Root CA
====================

The root CA is only used to issue sub-CA certificates.

To create one from scratch execute::

	tools/PKI/bin/create_root_ca

The new root CA will be created in::

    tools/PKI/root_ca

Generated files can be found at::

 - Private Key: tool/PKI/root_ca/private/root_ca_private_key.pem
 - PEM Certificate: tool/PKI/root_ca/root_ca_public_cert.pem
 - DER Certificate: tool/PKI/root_ca/root_ca_public_cert.der


Creating Issuing CA
===================

When we have a root CA we want to create sub-CA that will be used later
to issue certificates. In practice we want a different one for each
services with different authentication space.

To create one from scratch execute::

	tools/PKI/bin/create_issuing_ca SUB_CA_PREFIX

Where *SUB_CA_PREFIX* is the unique name to identify the CA.

The new CA will be created in::

	tools/PKI/SUB_CA_PREFIX_ca

Generated files can be found at::

 - Private Key: tool/PKI/SUB_CA_PREFIX_ca/private/ca_private_key.pem
 - PEM Certificate: tool/PKI/SUB_CA_PREFIX_ca/ca_public_cert.pem
 - DER Certificate: tool/PKI/SUB_CA_PREFIX_ca/ca_public_cert.der
 - CA Certificate Chain: tool/PKI/SUB_CA_PREFIX_ca/global_ca_public_cert.pem


Issue SSL Server Certificate
============================

A SSL server certificate most important parameter is the hostname it is
valid for. If the hostname is *flumotion.net*, the web browser will connect
without any complains only if the URL hostname is **EXACTLY** *flumotion.net*.
if it is *www.flumotion.net* the browser will complains. To use a certificate
with multiple domain us a wildcard in the hostname like::

	*.flumotion.net

This will work with *www.flumotion.net*, *mail.flumotion.net*, etc but **NOT**
for *sub.domain.flumotion.net*.

To issue a new SSL server certificate, execute::

	tools/PKI/bin/issu_cert SUB_CA_PREFIX CERT_PREFIX ssl_server HOSTNAME

Where *SUB_CA_PREFIX* is the prefix of the sub-CA to use to issue the
certificate, *CERT_PREFIX* is a unique prefix use to generate certificate
files and *HOSTNAME* is the hostname explain before.

Generated files can be found at::

 - Private Key: tool/PKI/SUB_CA_PREFIX_ca/private/CERT_PREFIX_private_key.pem
 - PEM Certificate: tool/PKI/SUB_CA_PREFIX_ca/certs/CERT_PREFIX_public_cert.pem
 - PKCS12: tool/PKI/SUB_CA_PREFIX_ca/certs/CERT_PREFIX.p12


Issue SSL Client Certificate
============================

A SSL client certificate contains client name surname and email.

To issue a new SSL server certificate, execute::

	tools/PKI/bin/issu_cert SUB_CA_PREFIX CERT_PREFIX ssl_client NAME SURNAME EMAIL

Generated files can be found at::

 - Private Key: tool/PKI/SUB_CA_PREFIX_ca/private/CERT_PREFIX_private_key.pem
 - PEM Certificate: tool/PKI/SUB_CA_PREFIX_ca/certs/CERT_PREFIX_public_cert.pem
 - PKCS12: tool/PKI/SUB_CA_PREFIX_ca/certs/CERT_PREFIX.p12
