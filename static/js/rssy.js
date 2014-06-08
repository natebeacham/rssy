var template = '<ul class="clearing-thumbs" data-clearing>' +
'<li><a href="HREF"><img title="CAPTION" data-caption="CAPTION" src="HREF"></a></li>' +
'</ul>';

$(function() {
	$('.summary img').each(function() {
		var href = $(this).attr('src');
		var caption = $(this).attr('title') || '';
		var rendered = template.replace(/HREF/g, href).replace(/CAPTION/g, caption);

		$(this).replaceWith(rendered);
	});
	$(document).foundation();
});
