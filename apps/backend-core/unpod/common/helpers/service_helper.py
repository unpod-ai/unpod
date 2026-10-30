from django.core.mail import EmailMessage


def send_email(
    subject,
    from_email,
    to,
    mail_body=None,
    mail_type="text",
    attachments=None,
    headers=None,
):
    """
    Send an email with optional HTML content and attachments.
    Args:
        subject (str): Subject of the email.
        from_email (str): Sender's email address.
        to (list): List of recipient email addresses.
        mail_body (str, optional): Body of the email. Defaults to None.
        mail_type (str, optional): Type of the email content ('html' or 'plain'). Defaults to 'html'.
        attachments (list, optional): List of attachments, each as a dict with 'filename', 'content', and 'mimetype'. Defaults to None.
        headers (dict, optional): Extra message headers (e.g. List-Unsubscribe). Defaults to None.
    Returns:
        tuple: (sent_count (int), error_message (str or None))
    """
    try:
        email = EmailMessage(subject, mail_body, from_email, to, headers=headers)

        if mail_type == "html":
            email.content_subtype = "html"  # HTML email body

        if attachments is None:
            attachments = []

        if len(attachments) > 0:
            for attachment in attachments:
                email.attach(
                    attachment["filename"],
                    attachment["content"],
                    attachment["mimetype"],
                )

        sent_count = email.send(fail_silently=False)
        return sent_count, None
    except Exception as e:
        print(f"Failed to send email: {str(e)}")
        return 0, str(e)
