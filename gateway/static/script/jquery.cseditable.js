(function($){
/*
 * Editable 1.3.1
 *
 * Copyright (c) 2009 Arash Karimzadeh (arashkarimzadeh.com)
 * Copyright (c) Code Sprinters (www.codesprinters.com)
 *
 * Licensed under the MIT (MIT-LICENSE.txt)
 * http://www.opensource.org/licenses/mit-license.php
 */
$.fn.cseditable = function(options) {
  var defaults = {
    onEdit: null,
    onSubmit: null,
    onReset: null,
    editClass: null,
    submit: null,
    cancel: null,
    cancelLink: null,
    startEditing: false,
    type: 'text', //text, textarea or select
    rows: 6,
    cols: 10,
    submitBy: 'blur', //blur,change,dblclick,click
    options: null
  };

  if (options=='disable') {
    return this.unbind('click', $.fn.cseditable._toEditable);
  }
  if (options=='enable') {
    return this.one('click', $.fn.cseditable._toEditable);
  }
  if (options=='destroy') {
    return this.unbind('click', $.fn.cseditable._toEditable)
      .data('cseditable.previous', null)
      .data('cseditable.current', null)
      .data('cseditable.options', null);
  }
  options = $.extend(defaults, options);
  this.data('cseditable.options', options);
  
  if (options.startEditing) {
    $.fn.cseditable._toEditable.call(this);
  } else {
    this.one('click', $.fn.cseditable._toEditable);
  
  }

  return false;
};

$.fn.cseditable._toEditable = function(ev) {
  if (ev && ($(ev.target).is('a') || $(ev.originalTarget).is('a'))) {
    $(this).cseditable('enable');
    return true;
  }
  var $this = $(this);
  $this.data('cseditable.current', $this.text());
  var opts = $this.data('cseditable.options');

  // Create form
  var form = $('<form action="javascript: null()"/>').addClass(opts.editClass)
      .appendTo($this.empty())
        .one('submit', function() {$.fn.cseditable._toNonEditableWithSave($this);return false;})
        .one('reset', function() {$.fn.cseditable._toNonEditableReset($this);return false;});
  var submitCancelDiv = $('<div></div>').addClass("submit-cancel-container").appendTo(form);
  // Submit Event
  if (opts.submit) {
    $('<button type="submit" />').appendTo(submitCancelDiv).html(opts.submit);
  } 
  
  // Cancel Event
  if (opts.cancel) {
    $('<input type="reset" />').appendTo(submitCancelDiv).html(opts.cancel);
  }

  // Cancel Event
  if (opts.cancelLink) {
    $('<a class="hide-form" href="#" />').appendTo(submitCancelDiv).html(opts.cancelLink).click(function() {
      form.trigger('reset'); 
      return false; 
    });
  }

  $('<div style="clear:both;height:1px;display:inline;"></div>').appendTo(form);

  $.cseditableFactory[opts.type].toEditable($this, form, opts);

  if (!opts.submit) {
    // FIXME: make this more elegant
    var change;
    form.find('input,select,textarea').bind(opts.submitBy, function(e) { 
      if ($.browser.msie || $.browser.opera) {      // IE and opera fires change event during keyboard navigation.. workaround of #892
        clearTimeout(change);
        change = setTimeout(function() {form.submit();}, 1000);
      } else {
        form.submit();
      }
    });
  }


  // Configure events, styles for changed content
  var inputField = $this.data('cseditable.previous',$this.data('cseditable.current'))
     .find(':input')
       .focus().select();

  inputField.bind($.browser.opera ? 'keypress' : 'keydown', function(e) {
    
    if (e.keyCode == 27) {
     form.trigger('reset'); 
     return false; 
    }
  });


  // Call User Function
  if ($.isFunction(opts.onEdit)) {
    opts.onEdit.call($this, {
      current: $this.data('cseditable.current'),
      previous: $this.data('cseditable.previous')
    });
  }

  return false;
};

$.fn.cseditable._toNonEditableWithSave = function($this) {
  var opts = $this.data('cseditable.options');
  
  var _revertOnError = function(envelope) {
    $this.data('cseditable.current', $this.data('cseditable.previous')).text( opts.type=='password' ? '*****' : $this.data('cseditable.previous'));
    if ($.isFunction(opts.errorHandler)) {
      opts.errorHandler.call($this, envelope);
    }
  };

  $this.one('click', $.fn.cseditable._toEditable)
    .data('cseditable.current', $.cseditableFactory[opts.type].getValue($this,opts))
    .text( opts.type=='password' ? '*****' : $this.data('cseditable.current'));

  // Call User Function
  if ($.isFunction(opts.onSubmit)) {
    opts.onSubmit.call($this, {
      current: $this.data('cseditable.current'),
      previous: $this.data('cseditable.previous')
    }, _revertOnError);
  }

  return false;
};

$.fn.cseditable._toNonEditableReset = function($this) {
  var opts = $this.data('cseditable.options');

  $this.one('click', $.fn.cseditable._toEditable)
    .data('cseditable.current', $this.data('cseditable.current'))
    .text( opts.type=='password' ? '*****' : $this.data('cseditable.current'));

  // Call User Function
  if ($.isFunction(opts.onReset)) {
    opts.onReset.call($this, {
      current: $this.data('cseditable.current'),
      previous: $this.data('cseditable.previous')
    });
  }
  return false;
};

$.cseditableFactory = {
  'text': {
    toEditable: function($this, form, options){
      $('<input type="text" />').prependTo(form)
             .val($this.data('cseditable.current'));
    },
    getValue: function($this, options){
      return $this.find('input:text').val();
    }
  },
  'password': {
    toEditable: function($this, form, options){
      $this.data('cseditable.current',$this.data('cseditable.password'));
      $this.data('cseditable.previous',$this.data('cseditable.password'));
      $('<input type="password"/>').prependTo(form)
                     .val($this.data('cseditable.current'));
    },
    getValue: function($this,options){
      $this.data('cseditable.password', $this.children().val());
      return $this.children().val();
    }
  },
  'textarea': {
    toEditable: function($this, form, options){
      var opts = $this.data('cseditable.options');
      $('<textarea/>').prependTo(form)
        .attr('rows', opts.rows).attr('cols', opts.cols)
              .val($this.data('cseditable.current'));
    },
    getValue: function($this,options){
      return $this.find('textarea').val();
    }
  },
  'select': {
    toEditable: function($this, form, options){
      var select = $('<select/>').prependTo(form);
      var current = $this.data('cseditable.current');
      $.each(options.options, function(key, value) {
          var is_selected = (current == value);
          $('<option/>').appendTo(select)
            .text(value).val(key)
              .attr('selected', is_selected);
      });
    },
    getValue: function($this, options){
      return $('option:selected', $this).val();
    }
  },
  'selectCheckbox': {
    toEditable: function($this, form, options) {
      var field = $('<input type="text" />').prependTo(form);
      var selected = [];
      if ($this.data('cseditable.current')) {
        selected = $this.data('cseditable.current').split(', ');
      }
      field.selectCheckbox({
        startOpen: true,
        selectList: options.options,
        select: selected,
        width: 175,
        paneClass: "checkbox-dropdown nosort"
      });
      field.selectCheckbox('fixPosition');
    },
    getValue: function($this, options) {  
      var v = $this.find('input:first').selectCheckbox('getSelectedLabels');
      return v;
    }
  }
};

})(jQuery);
