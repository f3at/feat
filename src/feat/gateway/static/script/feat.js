feat = {};

// Ajax requestes

feat.ajax = {};

feat.ajax.send = function(method, url, params) {
    if (typeof params != 'string') {
      params = JSON.stringify(params);
    };
    $.ajax({type: method,
	    url: url,
	    data: params,
	    success: feat.ajax._onSuccess,
	    error: feat.ajax._onError,
	    dataType: 'json',
	    contentType: 'application/json'
	});
};

feat.ajax._onSuccess = function(env) {
    console.log("Success: ", env);
    if (typeof env._redirect != 'undefined'){
	document.location = env._redirect;
    };
};

feat.ajax._onError = function(resp) {
    try {
	var envelope = $.parseJSON(resp);
	console.log('Error: ', envelope);
    } catch (e) {
	console.error('Failed unpacking the envelope', e);
	console.error('Response: ', resp);
    }
};

if (typeof console == 'undefined') {
    // define this functions in case we are running without the debugger
    console = {log: function() {},
	       error: function() {}};
}

// Inplace handlers

feat.inplace = {};

feat.inplace._onSubmit = function(value) {
  if (value.current != value.previous) {
    var $this = $(this);
    var url = $this.attr('rel');
    var params = {value: value.current};
    feat.ajax.send('PUT', url, params);
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

