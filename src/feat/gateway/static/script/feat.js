feat = {};

feat.ajax = {};

feat.ajax.send = function(method, url, params) {
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
    console.log("Succees: ", env);
};

feat.ajax._onError = function(resp) {
    try {
	var envelope = $.parseJSON(resp);
	console.log('Error: ', envelope);
    } catch (e) {
	console.error('Failed unpacking the envelope', e)
	console.error('Response: ', resp);
    }
};

if (typeof console == 'undefined') {
    // define this functions in case we are running without the debugger
    console = {log: function() {},
	       error: function() {}}
}
$(document).ready(function() {
    $('form.action_form').featform();
});

