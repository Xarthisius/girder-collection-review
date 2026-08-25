import template from '../templates/reviewItem.pug';
import '../stylesheets/review.styl';

const View = girder.views.View;
const FileListWidget = girder.views.widgets.FileListWidget;
const MetadataWidget = girder.views.widgets.MetadataWidget;
const { AccessType } = girder.constants;

/**
 * Read-only item detail, rendered inside the review page.
 *
 * Deliberately not the core ItemView: navigating to the core ``item/:id`` route would
 * trigger ``g:navigateTo`` with no layout option, and App.navigateTo resets to the default
 * layout in that case -- restoring the header and navigation the review page has hidden.
 */
const ReviewItemView = View.extend({
    initialize: function (settings) {
        this.item = settings.item;

        // Needs the full item document (size, meta, ...); the list only carries a summary.
        // ignoreError suppresses core's default handler, which turns any 401 into a login
        // modal floating over the chrome-free review page.
        this.item.on('g:fetched', this.render, this).fetch({ ignoreError: true });
    },

    render: function () {
        this.$el.html(template({ item: this.item }));

        this.fileListWidget = new FileListWidget({
            el: this.$('.g-review-item-files'),
            parentView: this,
            item: this.item
        });

        this.metadataWidget = new MetadataWidget({
            el: this.$('.g-review-item-metadata'),
            parentView: this,
            item: this.item,
            // MetadataWidget self-gates its edit affordances on this value; a reviewer has
            // READ, so it renders as a plain table.
            accessLevel: AccessType.READ
        });

        return this;
    }
});

export default ReviewItemView;
