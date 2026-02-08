import { LightningElement, api } from 'lwc';
import Id from '@salesforce/user/Id';
import getSessionInfo from '@salesforce/apex/PdfEditorController.getSessionInfo';

export default class PdfEditorEmbed extends LightningElement {
    @api recordId; // Account ID from the record page
    userId = Id; // Current user ID
    isLoading = true;
    hasError = false;
    sessionId = null;
    instanceUrl = null;

    // Heroku app base URL
    herokuBaseUrl = 'https://pdfeditorsalesforce-49dc376497fd.herokuapp.com';

    get iframeUrl() {
        if (this.recordId && this.userId && this.sessionId && this.instanceUrl) {
            // Build URL with session parameters
            const url = new URL(`${this.herokuBaseUrl}/${this.recordId}/${this.userId}`);
            url.searchParams.set('sfSession', this.sessionId);
            url.searchParams.set('sfOrg', this.instanceUrl);
            return url.toString();
        }
        return null;
    }

    handleIframeLoad() {
        this.isLoading = false;
    }

    handleIframeError() {
        this.isLoading = false;
        this.hasError = true;
    }

    connectedCallback() {
        // Get Salesforce session info
        this.loadSessionInfo();

        // Listen for messages from the iframe
        window.addEventListener('message', this.handleMessage.bind(this));
    }

    disconnectedCallback() {
        // Clean up event listener
        window.removeEventListener('message', this.handleMessage.bind(this));
    }

    loadSessionInfo() {
        getSessionInfo()
            .then(result => {
                this.sessionId = result.sessionId;
                this.instanceUrl = result.instanceUrl;
            })
            .catch(error => {
                console.error('Error getting session info:', error);
                this.hasError = true;
                this.isLoading = false;
            });
    }

    handleMessage(event) {
        // Verify the message is from your Heroku app
        if (event.origin !== this.herokuBaseUrl) {
            return;
        }

        // Handle messages from your PDF editor
        console.log('Message from PDF Editor:', event.data);

        // You can add custom logic here to handle specific messages
        // For example: if the user saves a PDF, you could refresh Salesforce data
    }
}
