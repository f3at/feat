===================
How to create a PKI
===================

**WARNING**:

	This describes a quick, simple and **UNSAFE** way of creating a [PKI]_.
        This is acceptable for development purposes, but a proper PKI
        infrastructure should be used for production.

The Quick and Lazy Way
======================

To create a new CA and certificates from scratch (assuming the current directory
is the root of your feat checkout)::

	cd tools/PKI
	bin/create_config feat.conf
	bin/create_root_ca
	bin/create_issuing_ca tunneling
	bin/issue_cert tunneling tunneling ssl_server *.flumotion.fluendo.lan
	bin/create_issuing_ca gateway
	bin/issue_cert gateway gateway ssl_server *.flumotion.fluendo.lan
	bin/issue_cert gateway dummy ssl_client $NAME $EMAIL admin

The generated files can be found there:

 - Tunneling Server PKCS12::

   ./tunneling_ca/certs/tunneling.p12

 - Gateway Server PKCS12::

   ./gateway_ca/certs/gateway.p12

 - Gateway Dummy Client PKCS12::

   ./gateway_ca/certs/dummy.p12


PKI and Feat
============

Feat needs keys and certificates for securing the gateway and the
tunneling backend. Both components use SSL and verify that the other side's
certificate has been issued by its own CA.

In practice this means that Feat needs two CA's or sub-CA's: one for the gateway
and one for tunneling. This is required to prevent a user with a valid gateway
certificate to be able to push random messages through a tunnel.

To facilitate maintenance, Feat is using the PKCS12 format. This format allows
to store the private key, the certificate and the CA certification chain
all in only one file.

In theory, each feat service should have its own PKCS12 for gateway and
tunneling, but for development we could use the same for all services.

To be able to connect to the gateway using a web browser, one should import
a PKCS12 issued by the gateway CA and set the gateway CA as trusted.

To prevent the browser to ask for confirmation every time it connects to
a gateway server with different hostname, one should generate a gateway
certificate with a common name matching the gateway's hostname. The default one
uses \*.flumotion.fluendo.lan, so when the CA is marked as trusted, all
services hosted on any sub-domain of flumotion.fluendo.lan will not
ask for confirmation.


Creating configuration files
============================

Needed configuration files are generated from a set of template and
a configuration file containing the variable that must be substituted.

To customise the PKI copy the file tools/PKI/feat.conf to another name,
update it, and use it to generate the configuration with the command::

    tools/PKI/bin/create_config $CONFIG_FILE


Creating the Root CA
====================

The root CA is only used to issue sub-CA certificates.
Only one root CA should be generated and reused for all sub-CA's.

To create one from scratch execute::

    tools/PKI/bin/create_root_ca

The new root CA will be created in::

    tools/PKI/root_ca

Generated files can be found at:

 - Private Key::

    tools/PKI/root_ca/private/root_ca_private_key.pem

 - PEM Certificate::

    tools/PKI/root_ca/root_ca_public_cert.pem

 - DER Certificate::

    tools/PKI/root_ca/root_ca_public_cert.der


Creating Issuing CA
===================

When we have a root CA we want to create sub-CA that will be used later
to issue certificates.

In practice we want a different one for each
service in a different authentication space (gateway versus tunneling,
production versus staging, ...)

To create one from scratch execute::

	tools/PKI/bin/create_issuing_ca $SUB_CA_PREFIX

Where *$SUB_CA_PREFIX* is the unique name to identify the CA.

The new CA will be created in::

	tools/PKI/${SUB_CA_PREFIX}_ca

Generated files can be found at:

 - Private Key::

    tools/PKI/${SUB_CA_PREFIX}_ca/private/ca_private_key.pem

 - PEM Certificate::

    tools/PKI/${SUB_CA_PREFIX}_ca/ca_public_cert.pem

 - DER Certificate::

    tools/PKI/${SUB_CA_PREFIX}_ca/ca_public_cert.der

 - CA Certificate Chain::

    tools/PKI/${SUB_CA_PREFIX}_ca/global_ca_public_cert.pem


The PEM certificate can be used with tools like curl (using --cacert) to
verify the server keys issued under this sub-CA.

When testing with curl, use the sub-CA PEM certificate::

     --cacert ${SUB_CA_PREFIX}_ca/ca_public_cert.pem


FIXME: global_ca_public_cert.pem also works; why should the other one be
used ?


Issue SSL Server Certificate
============================

The most important attribute of an SSL server certificate
is the hostname it is valid for.
If the hostname is *flumotion.net*, the web browser will only connect
without any complaints if the URL hostname is **EXACTLY** *flumotion.net*.
if it is *www.flumotion.net* the browser will complain. To use a certificate
with multiple domains, use a wildcard in the hostname like::

	*.flumotion.net

This will work with *www.flumotion.net*, *mail.flumotion.net*, etc but **NOT**
for *sub.domain.flumotion.net*.

To issue a new SSL server certificate, execute::

	tools/PKI/bin/issue_cert $SUB_CA_PREFIX $CERT_PREFIX ssl_server $HOSTNAME

Where *$SUB_CA_PREFIX* is the prefix of the sub-CA to use to issue the
certificate, *$CERT_PREFIX* is a unique prefix used to generate certificate
files and *$HOSTNAME* is the hostname as explained before.

Generated files can be found at:

 - Private Key::

    tools/PKI/${SUB_CA_PREFIX}_ca/private/${CERT_PREFIX}_private_key.pem

 - PEM Certificate::

    tools/PKI/${SUB_CA_PREFIX}_ca/certs/${CERT_PREFIX}_public_cert.pem

 - PKCS12::

    tools/PKI/${SUB_CA_PREFIX}_ca/certs/${CERT_PREFIX}.p12


Issue SSL Client Certificate
============================

A SSL client certificate contains client name, surname and email.

To issue a new SSL client certificate, execute::

	tools/PKI/bin/issue_cert $SUB_CA_PREFIX $CERT_PREFIX ssl_client $NAME $EMAIL $ROLE1 $ROLE2 $ROLE3

Generated files can be found at:

 - Private Key::

    tools/PKI/${SUB_CA_PREFIX}_ca/private/${CERT_PREFIX}_private_key.pem

 - PEM Certificate::

    tools/PKI/${SUB_CA_PREFIX}_ca/certs/${CERT_PREFIX}_public_cert.pem

 - PKCS12::

    tools/PKI/${SUB_CA_PREFIX}_ca/certs/${CERT_PREFIX}.p12

When testing with curl, use the PEM certificate and Private Key::

     --cert ./${CERT_PREFIX}_public_cert.pem --key ${CERT_PREFIX}_private_key.pem

to present the client certificate to the server.

Chrome
------
To use this client certificate in Chrome:
 - Go to Preferences>Under the Hood>HTTPS/SSL and click Manage Certificates
 - Click Import
 - Browse to the ${CERT_PREFIX}.p12 file you generated
 - Go to Authorities, and select the authority for its Root CA which by default
   is untrusted
 - Click Edit...
 - Check 'Trust this certificate for identifying websites'

FIXME: should each separate client we want to give access get its own client
key ?

References
==========

.. [PKI] `<http://en.wikipedia.org/wiki/Public_key_infrastructure>`_
