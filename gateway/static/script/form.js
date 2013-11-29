(function($){

$.fn.featform = function(options) {
    $(this).each(
	function(index) {
            var $this = $(this);
	    var defaults = {
		url: $this.attr('action'),
		method: $this.attr('method')
	    };
	    var opts = $.extend(defaults, options);

	    $this.data('featform.options', opts);
	    $this.bind('submit', $.fn.featform._onSubmit);

            var spinner = $.fn.featform._generateSpinner();
	    $this.data('featform.spinner', spinner);
	    spinner.insertAfter($this.find('input:submit'));
    });
};

$.fn.featform._generateSpinner = function() {
    var spinner = $("<image src='/static/images/spinner.gif>");
    spinner.css('display', 'none');
    spinner.css('height', '25px');
    spinner.css('width', '25px');
    spinner.css('float', 'left');
    return spinner;
};


$.fn.featform._renderJSONList = function(json) {
    var html = "<ul>";
    $.each(
	json,
	function(key, value) {
	    html += "<li><span class='key'>" + key + "</span>";
	    if (key == 'href') {
		value = "<a href='" + value + "'>Follow</a>";
	    };

	    html += "<span class='value'>" + value + "</span></li>";
	});
    html += "</ul>";
    return html;
};

$.fn.featform._reset = function() {
    $(this).trigger("reset");
    $.fn.featform._removeErrors.call(this);
};

$.fn.featform._removeErrors = function() {
    $(this).find('.invalid').removeClass('invalid');
    $(this).find('.explanation').remove();
};

$.fn.featform._onSubmit = function(ev) {
    ev.preventDefault();
    ev.stopPropagation();

    var $this = $(ev.target);
    var params = {};

    var options = $this.data('featform.options');
    if (options.method == 'GET') {
        var url = options.url;
        var serialized  = '';
        var array = $this.serializeArray();
        for (var i in array) {
            if (array[i].value) {
                if (serialized) serialized += '&';
                serialized += array[i].name;
                serialized += "=";
                serialized += array[i].value;
            }
        }
        if (serialized) {
            url = url + "?" + serialized;
        }
        document.location = url;
        return;
    }
    
    var array = $this.serializeArray();

    $.each(
	array,
	function(i, element) {
	    if (element.value != '') {
		// split names on dot, put the value inside the nested
		// structure like a.b.c -> {a:{b:{c: value}}}
		var parts = element.name.split('.');
		var current = params;
		while (parts.length > 1) {
		    var name = parts.shift();
		    if (typeof(current[name]) == 'undefined') {
			current[name] = {};
		    };
		    current = current[name];
		}
		current[parts[0]] = element.value;
	    }
	});

    var spinner = $this.data('featform.spinner');
    spinner.show();

    var success = function(envelope) {
	spinner.hide();
	$.fn.featform._reset.call($this);
	var html = "<H3>Action successful</H3><div class='response'>";
	if (typeof envelope == "object") {
	    html += $.fn.featform._renderJSONList(envelope);
	} else {
	    html += $.fn.featform._renderJSONList({"Result:": envelope});
	}
	html += "</div>";
	$.facebox(html);
    };

    var getReason = function(envelope, subject) {
	if (envelope.error == "invalid_parameters") {
	    return envelope.reasons[subject];
	} else if (envelope.error == "missing_parameters") {
	    return "Is required and missing.";
	};
	return "Unknown";
    };

    var failure = function(envelope) {
	spinner.hide();
	if (envelope.error == "invalid_parameters" ||
	    envelope.error == "missing_parameters") {
	    $.each(
		envelope.subjects,
		function(index, subject) {
		    var input = $this.find("input[name='" + subject + "']");
		    input.addClass('invalid');
		    var reason = getReason(envelope, subject);
		    var explanation = $("<span class='explanation'>" +
					reason + "</span>");
		    explanation.insertAfter(input);
		});
	} else {
	    var html = "<H3>Action failed</H3><div class='response'>";
	    html += $.fn.featform._renderJSONList(envelope) + "</div>";
	    $.facebox(html);
	}
    };

    $.fn.featform._removeErrors.call($this);
    feat.ajax.send(options.method, options.url, params, success, failure);
};

})(jQuery);
