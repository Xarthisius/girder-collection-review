import actionsTemplate from '../templates/collectionActions.pug';

import ReviewManageWidget from './ReviewManageWidget';

const $ = girder.$;
const CollectionView = girder.views.body.CollectionView;
const { AccessType } = girder.constants;
const { wrap } = girder.utilities.PluginUtils;

/**
 * Add a "Manage review" entry to the collection Actions menu for collection admins.
 */
wrap(CollectionView, 'render', function (render) {
    render.call(this);

    if (this.model && this.model.getAccessLevel() >= AccessType.ADMIN) {
        this.$('.g-collection-actions-menu').append(actionsTemplate());
    }

    return this;
});

CollectionView.prototype.events['click .g-collection-manage-review'] = function () {
    new ReviewManageWidget({
        el: $('#g-dialog-container'),
        collection: this.model,
        parentView: this
    }).render();
};
