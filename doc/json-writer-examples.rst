==========================
JSON Writer Output Examples
==========================


IErrorPayload
=============


Generic Server Error
--------------------

::

  {
   "type": "error",
   "error": "generic",
   "message": "File Error",
   "debug": "No such file or directory: /spam/bacon",
   "trace": "Traceback (most recent call last)\n in spam()\n in bacon()\n Exception: No such file or directory: /spam/bacon"
  }


HTTP Protocol Error
-------------------

::

  {
   "type": "error",
   "error": "http",
   "code": 404,
   "message": "Resource Not Found"
  }


Missing Action Parameters
-------------------------

::

  {
   "type": "error",
   "error": "missing_parameters",
   "message": "Action foo is missing parameter(s): spam, bacon",
   "subjects": ["spam", "bacon"]
  }


Unknown Action Parameters
-------------------------

::

  {
   "type": "error",
   "error": "unknown_parameters",
   "message": "Action foo do not expects parameter(s): beans, egg"
   "subjects": ["beans", "egg"]
  }


Invalid Action Parameters
-------------------------

::

  {
   "type": "error",
   "error": "invalid_parameters",
   "message": "Action foo parameter(s) invalid: spam, bacon"
   "subjects": ["spam", "bacon"],
   "reasons": {"spam": "Not a string: 4",
               "bacon": "Not an integer: 'X'}
  }


Other Action Parameter Error
----------------------------

::

  {
   "type": "error",
   "error": "parameter_error",
   "message": "Some unexpected error"
   "subjects": ["value"]
  }
