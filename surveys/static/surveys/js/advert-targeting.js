/* Advertiser / Direct Marketing admin: pick a country first, then the category
 * dropdown is repopulated with only that country's survey categories.
 * The endpoint lives on the same admin page path, so this works on both the
 * custom admin site and the default one without hardcoding a URL.
 */
(function () {
    'use strict';

    function ready(fn) {
        if (document.readyState !== 'loading') {
            fn();
        } else {
            document.addEventListener('DOMContentLoaded', fn);
        }
    }

    ready(function () {
        var countrySelect = document.getElementById('id_countries');
        var categorySelect = document.getElementById('id_categories');
        if (!countrySelect || !categorySelect) return;

        // /admin/surveys/advertiser/add/      -> /admin/surveys/advertiser/
        // /admin/surveys/advertiser/5/change/ -> /admin/surveys/advertiser/
        var base = window.location.pathname.replace(/(?:add|\d+\/change)\/$/, '');
        var endpoint = base + 'get-categories/';

        // Remember what was selected so an existing advert keeps its categories.
        var initialValues = Array.prototype.map.call(
            categorySelect.selectedOptions, function (o) { return o.value; }
        );

        function selectedCountryIds() {
            return Array.prototype.map.call(
                countrySelect.selectedOptions, function (o) { return o.value; }
            ).filter(Boolean);
        }

        /* "Select all" / "Clear" controls above a multi-select.
         * Clear is the meaningful one: an empty field targets everything,
         * including countries or categories added in the future. Select all
         * pins the advert to exactly what exists today.
         */
        function addToolbar(select, label, onChange) {
            var bar = document.createElement('p');
            bar.className = 'advert-targeting-tools';
            bar.style.margin = '0 0 6px';
            bar.style.fontSize = '11px';

            function makeLink(text, handler) {
                var a = document.createElement('a');
                a.href = '#';
                a.textContent = text;
                a.style.marginRight = '12px';
                a.addEventListener('click', function (event) {
                    event.preventDefault();
                    handler();
                    if (onChange) onChange();
                });
                return a;
            }

            bar.appendChild(makeLink('Select all ' + label, function () {
                Array.prototype.forEach.call(select.options, function (opt) {
                    if (!opt.disabled) opt.selected = true;
                });
            }));

            bar.appendChild(makeLink('Clear', function () {
                Array.prototype.forEach.call(select.options, function (opt) {
                    opt.selected = false;
                });
            }));

            var hint = document.createElement('span');
            hint.style.color = '#666';
            hint.textContent = 'empty = all ' + label + ', including any added later';
            bar.appendChild(hint);

            select.parentNode.insertBefore(bar, select);
        }

        // A multi-select has no blank option, so show the hint as a disabled row.
        function setPlaceholder(text) {
            categorySelect.innerHTML = '';
            var opt = document.createElement('option');
            opt.value = '';
            opt.textContent = text;
            opt.disabled = true;
            categorySelect.appendChild(opt);
        }

        function loadCategories(countryIds, keepValues) {
            if (!countryIds.length) {
                setPlaceholder('Select one or more countries first');
                return;
            }

            setPlaceholder('Loading...');
            var params = countryIds.map(function (id) {
                return 'country_id=' + encodeURIComponent(id);
            }).join('&');
            fetch(endpoint + '?' + params, { credentials: 'same-origin' })
                .then(function (response) { return response.json(); })
                .then(function (categories) {
                    categorySelect.innerHTML = '';
                    categories.forEach(function (category) {
                        var opt = document.createElement('option');
                        opt.value = category.id;
                        opt.textContent = category.name;
                        if (keepValues && keepValues.indexOf(String(category.id)) !== -1) {
                            opt.selected = true;
                        }
                        categorySelect.appendChild(opt);
                    });
                    if (!categories.length) {
                        setPlaceholder('No categories for the selected countries');
                    }
                })
                .catch(function () {
                    setPlaceholder('Could not load categories');
                });
        }

        function refreshCategories() {
            // Keep any still-valid choices when the country set changes.
            var keep = Array.prototype.map.call(
                categorySelect.selectedOptions, function (o) { return o.value; }
            );
            loadCategories(selectedCountryIds(), keep);
        }

        countrySelect.addEventListener('change', refreshCategories);

        // Selecting all countries must also refresh the category list.
        addToolbar(countrySelect, 'countries', refreshCategories);
        addToolbar(categorySelect, 'categories', null);

        // Populate on load so editing an existing advert shows its categories.
        loadCategories(selectedCountryIds(), initialValues);
    });
})();
