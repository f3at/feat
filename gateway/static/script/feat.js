feat = {};

// Ajax requestes

feat.ajax = {};

feat.ajax.send = function(method, url, params, success, failure) {
    if (typeof params != 'string') {
      params = JSON.stringify(params);
    };
    $.ajax({type: method,
	    url: url,
	    data: params,
	    success: feat.ajax._onSuccessBuilder(success),
	    error: feat.ajax._onErrorBuilder(failure),
	    dataType: 'json',
	    contentType: 'application/json'
	});
};

feat.ajax._onSuccessBuilder = function(callback) {

    var handler = function(env) {
	console.log("Success: ", env);
	if (typeof(callback) == 'function') {
	    callback(env);
	};
    };
    return handler;
};

feat.ajax._onErrorBuilder = function(callback) {

    var handler = function(resp) {
	try {
	    var envelope = $.parseJSON(resp.responseText);
	    console.log('Error: ', envelope);
	} catch (e) {
	    console.error('Failed unpacking the envelope', e);
	    console.error('Response: ', resp);
	    return;
	}
	if (typeof(callback) == 'function') {
	    callback(envelope);
	};
    };
    return handler;
};

if (typeof console == 'undefined') {
    // define this functions in case we are running without the debugger
    console = {log: function() {},
	       error: function() {}};
}

// Inplace handlers

feat.inplace = {};

feat.inplace._onSubmit = function(value, errorHandler) {

  var setReturnedValue = function(value) {
    var $this = $(this);
    $this.text(value);
  };

  if (value.current != value.previous) {
    var $this = $(this);
    var url = $this.attr('rel');
    var params = {value: value.current};
    feat.ajax.send('PUT', url, params, setReturnedValue, errorHandler);
  };
};

// Application init

$(document).ready(function() {
    $('form.action_form').featform();
    $('.inplace').cseditable({
       type: 'text',
       submit: 'OK',
       cancelLink: "Cancel",
       editClass: "editor_field",
       onSubmit: feat.inplace._onSubmit
    });
});

