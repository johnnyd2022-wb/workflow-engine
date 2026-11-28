(function () {
  'use strict';
  if (window.ProductImage) return;

  function thumbnail(url, size, alt) {
    var frame = document.createElement('span');
    frame.className = 'product-image' + (size ? ' product-image--' + size : '');
    if (!url || !/^\/api\/core\/(?:processes|inventory)\/[a-f0-9-]{36}\/product-image(?:\?v=\d+)?$/.test(url)) {
      frame.setAttribute('aria-hidden', 'true');
      return frame;
    }
    var image = document.createElement('img');
    image.width = 48;
    image.height = 48;
    image.loading = size === 'editor' ? 'eager' : 'lazy';
    image.decoding = 'async';
    image.alt = alt || '';
    image.src = url;
    frame.appendChild(image);
    return frame;
  }

  function thumbnailForLots(lots) {
    var first = lots[0];
    var key = first?.product_image_id;
    return thumbnail(key && lots.every(function (lot) { return lot.product_image_id === key; })
      ? first.product_image_url : '');
  }

  document.addEventListener('error', function (event) {
    if (event.target instanceof HTMLImageElement && event.target.parentElement?.classList.contains('product-image')) {
      event.target.remove();
    }
  }, true);

  document.addEventListener('click', function (event) {
    var trigger = event.target.closest('[data-product-image-open]');
    if (!trigger) return;
    var editor = trigger.closest('[data-product-image-editor]');
    var sheet = editor.querySelector('dialog');
    sheet.querySelector('[role=alert]').textContent = '';
    sheet.querySelector('form').reset();
    sheet.showModal();
  });

  document.addEventListener('submit', async function (event) {
    var form = event.target.closest('[data-product-image-form]');
    if (!form) return;
    event.preventDefault();
    var action = event.submitter?.value;
    var sheet = form.closest('dialog');
    if (action === 'cancel') {
      sheet.close();
      return;
    }
    if (form.dataset.saving === 'true') return;

    var editor = form.closest('[data-product-image-editor]');
    var trigger = editor.querySelector('[data-product-image-open]');
    var error = form.querySelector('[role=alert]');
    var file = form.elements.file.files[0];
    if (action !== 'remove' && !file) {
      error.textContent = 'Choose a final product image.';
      return;
    }

    var body = new FormData();
    if (file && action !== 'remove') body.append('file', file);
    var buttons = Array.from(form.querySelectorAll('button'));
    buttons.forEach(function (button) { button.disabled = true; });
    form.dataset.saving = 'true';
    error.textContent = '';
    var headers = { 'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || '' };
    try {
      var removing = action === 'remove';
      var response = await fetch(editor.dataset.productImageEditor, {
        method: removing ? 'DELETE' : 'PUT',
        credentials: 'same-origin',
        headers: headers,
        body: removing ? undefined : body,
      });
      if (!response.ok) {
        var failure = await response.json().catch(function () { return {}; });
        throw new Error(failure.errors?.file || (response.status === 413
          ? 'Choose an image of 10 MB or less.' : 'Could not save the final product image. Try again.'));
      }
      var url = removing ? '' : (await response.json()).product_image_url + '?v=' + Date.now();
      editor.querySelector('.product-image').replaceWith(thumbnail(url, 'editor', 'Final product'));
      editor.toggleAttribute('data-has-image', !removing);
      form.querySelector('[value=remove]').hidden = removing;
      trigger.setAttribute('aria-label', removing ? 'Add final product image' : 'Change final product image');
      editor.querySelector('[role=status]').textContent = removing ? 'Product image removed.' : 'Product image saved.';
      sheet.close();
    } catch (errorResponse) {
      error.textContent = errorResponse.message;
    } finally {
      buttons.forEach(function (button) { button.disabled = false; });
      delete form.dataset.saving;
    }
  });

  document.addEventListener('cancel', function (event) {
    if (event.target.querySelector('[data-product-image-form][data-saving=true]')) event.preventDefault();
  }, true);

  window.ProductImage = { thumbnail: thumbnail, thumbnailForLots: thumbnailForLots };
}());
