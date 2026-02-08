public with sharing class PdfEditorController {

    @AuraEnabled(cacheable=false)
    public static Map<String, String> getSessionInfo() {
        Map<String, String> sessionInfo = new Map<String, String>();

        try {
            // Get session ID
            String sessionId = UserInfo.getSessionId();

            // Get instance URL using DomainCreator
            String instanceUrl = System.DomainCreator.getOrgMyDomainHostname();
            if (instanceUrl != null && !instanceUrl.startsWith('http')) {
                instanceUrl = 'https://' + instanceUrl;
            }

            // Get org ID
            String orgId = UserInfo.getOrganizationId();

            sessionInfo.put('sessionId', sessionId);
            sessionInfo.put('instanceUrl', instanceUrl);
            sessionInfo.put('orgId', orgId);

            return sessionInfo;

        } catch (Exception e) {
            throw new AuraHandledException('Error getting session info: ' + e.getMessage());
        }
    }
}
