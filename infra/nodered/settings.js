const credentialSecret = process.env.NODE_RED_CREDENTIAL_SECRET;

if (!credentialSecret) {
    throw new Error("NODE_RED_CREDENTIAL_SECRET must be set.");
}

module.exports = {
    credentialSecret,
};
