// draft-zyp-json-schema-03
// http://json-schema.org

{"name": "IErrorPayload",
 "type": "object",
 "properties": {
   "type": {
     "type": "string",
     "enum": ["error"],
     "required": true},
   "error: {
     "type": "string",
     "enum": ["generic", "http", "parameter_error", "missing_parameters",
              "unknown_parameters", "invalid_parameters"],
     "required": true},
   "code": {
     "type": "integer",
     "required": false},
   "message": {
     "type": "string",
     "required": false},
   "subjects": {
     "type": "array",
     "items":  {"type": "string"},
     "required": false},
   "subjects": {
     "type": "array",
     "items":  {"type": "string"},
     "required": false},
   "reasons": {
     "type": "object",
     "patternProperties": {
       ".*": {"type": "string"}}
     "required": false},
   "debug": {
     "type": "string",
     "required": false},
   "trace": {
     "type": "string",
     "required": false}}
}
