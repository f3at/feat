(function($){

$.fn.featform = function(options) {
    var $this = $(this);
    var defaults = {
	url: $this.attr('action'),
	method: $this.attr('method')
    };
    options = $.extend(defaults, options);

    $this.data('featform.options', options);

    $this.bind('submit', $.fn.featform._onSubmit)

    return false;
};

$.fn.featform._onSubmit = function(ev) {
    ev.preventDefault();
    ev.stopPropagation();

    var $this = $(ev.target);

    var params = {};
    var array = $this.serializeArray();
    $.each(array, function(i, element) {
	    params[element.name] = element.value;
	});

    options = $this.data('featform.options')
    feat.ajax.send(options.method, options.url, params)
};

})(jQuery);
