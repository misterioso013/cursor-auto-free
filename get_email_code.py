import logging
import time
import re
from config import Config
import requests
import email
import imaplib


class EmailVerificationHandler:
    def __init__(self):
        self.imap = Config().get_imap()
        self.username = Config().get_temp_mail()
        self.epin = Config().get_temp_mail_epin()
        self.session = requests.Session()
        self.emailExtension = Config().get_temp_mail_ext()

    def get_verification_code(self, max_retries=5, retry_interval=30):
        """
        Obtém o código de verificação com mecanismo de retry melhorado.
        """
        for attempt in range(max_retries):
            try:
                logging.info(f"Tentativa {attempt + 1}/{max_retries} de obter código...")

                if not self.imap:
                    logging.info("Usando tempmail.plus para verificação...")
                    verify_code, first_id = self._get_latest_mail_code()
                    if verify_code:
                        logging.info(f"Código encontrado: {verify_code}")
                        self._cleanup_mail(first_id)
                        return verify_code
                    logging.warning("Nenhum código encontrado nesta tentativa")
                else:
                    logging.info("Usando IMAP para verificação...")
                    verify_code = self._get_mail_code_by_imap()
                    if verify_code:
                        logging.info(f"Código encontrado via IMAP: {verify_code}")
                        return verify_code
                    logging.warning("Nenhum código encontrado via IMAP")

                if attempt < max_retries - 1:
                    logging.info(f"Aguardando {retry_interval} segundos antes da próxima tentativa...")
                    time.sleep(retry_interval)

            except Exception as e:
                logging.error(f"Erro ao obter código: {str(e)}")
                if attempt < max_retries - 1:
                    logging.info(f"Tentando novamente em {retry_interval} segundos...")
                    time.sleep(retry_interval)

        raise Exception(f"Não foi possível obter o código após {max_retries} tentativas")

    def _get_mail_code_by_imap(self, retry = 0):
        if retry > 0:
            time.sleep(3)
        if retry >= 20:
            raise Exception("获取验证码超时")
        try:
            # 连接到IMAP服务器
            mail = imaplib.IMAP4_SSL(self.imap['imap_server'], self.imap['imap_port'])
            mail.login(self.imap['imap_user'], self.imap['imap_pass'])
            mail.select(self.imap['imap_dir'])

            status, messages = mail.search(None, 'FROM', '"no-reply@cursor.sh"')
            if status != 'OK':
                return None

            mail_ids = messages[0].split()
            if not mail_ids:
                # 没有获取到，就在获取一次
                return self._get_mail_code_by_imap(retry=retry + 1)

            latest_mail_id = mail_ids[-1]

            # 获取邮件内容
            status, msg_data = mail.fetch(latest_mail_id, '(RFC822)')
            if status != 'OK':
                return None

            raw_email = msg_data[0][1]
            email_message = email.message_from_bytes(raw_email)

            # 提取邮件正文
            body = self._extract_imap_body(email_message)
            if body:
                # 使用正则表达式查找6位数字验证码
                code_match = re.search(r"\b\d{6}\b", body)
                if code_match:
                    code = code_match.group()
                    # 删除邮件
                    mail.store(latest_mail_id, '+FLAGS', '\\Deleted')
                    mail.expunge()
                    mail.logout()
                    # print(f"找到的验证码: {code}")
                    return code
            # print("未找到验证码")
            mail.logout()
            return None
        except Exception as e:
            print(f"发生错误: {e}")
            return None

    def _extract_imap_body(self, email_message):
        # 提取邮件正文
        if email_message.is_multipart():
            for part in email_message.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))
                if content_type == "text/plain" and "attachment" not in content_disposition:
                    charset = part.get_content_charset() or 'utf-8'
                    try:
                        body = part.get_payload(decode=True).decode(charset, errors='ignore')
                        return body
                    except Exception as e:
                        logging.error(f"解码邮件正文失败: {e}")
        else:
            content_type = email_message.get_content_type()
            if content_type == "text/plain":
                charset = email_message.get_content_charset() or 'utf-8'
                try:
                    body = email_message.get_payload(decode=True).decode(charset, errors='ignore')
                    return body
                except Exception as e:
                    logging.error(f"解码邮件正文失败: {e}")
        return ""

    def _get_latest_mail_code(self):
        """
        Obtém o código mais recente do tempmail.plus com melhor tratamento de erros.
        """
        try:
            mail_list_url = f"https://tempmail.plus/api/mails?email={self.username}{self.emailExtension}&limit=20&epin={self.epin}"
            logging.info(f"Consultando emails em: {mail_list_url}")

            mail_list_response = self.session.get(mail_list_url)
            if mail_list_response.status_code != 200:
                logging.error(f"Erro na API: Status {mail_list_response.status_code}")
                return None, None

            mail_list_data = mail_list_response.json()
            if not mail_list_data.get("result"):
                logging.warning("Nenhum email encontrado")
                return None, None

            first_id = mail_list_data.get("first_id")
            if not first_id:
                logging.warning("Nenhum ID de email encontrado")
                return None, None

            mail_detail_url = f"https://tempmail.plus/api/mails/{first_id}?email={self.username}{self.emailExtension}&epin={self.epin}"
            logging.info("Obtendo detalhes do email...")

            mail_detail_response = self.session.get(mail_detail_url)
            if mail_detail_response.status_code != 200:
                logging.error(f"Erro ao obter detalhes: Status {mail_detail_response.status_code}")
                return None, None

            mail_detail_data = mail_detail_response.json()
            if not mail_detail_data.get("result"):
                logging.warning("Nenhum detalhe de email encontrado")
                return None, None

            mail_text = mail_detail_data.get("text", "")
            mail_subject = mail_detail_data.get("subject", "")
            logging.info(f"Email encontrado com assunto: {mail_subject}")

            code_match = re.search(r"\b\d{6}\b", mail_text)
            if code_match:
                code = code_match.group()
                logging.info(f"Código extraído com sucesso: {code}")
                return code, first_id

            logging.warning("Nenhum código encontrado no corpo do email")
            return None, None

        except Exception as e:
            logging.error(f"Erro ao processar email: {str(e)}")
            return None, None

    def _cleanup_mail(self, first_id):
        # 构造删除请求的URL和数据
        delete_url = "https://tempmail.plus/api/mails/"
        payload = {
            "email": f"{self.username}{self.emailExtension}",
            "first_id": first_id,
            "epin": f"{self.epin}",
        }

        # 最多尝试5次
        for _ in range(5):
            response = self.session.delete(delete_url, data=payload)
            try:
                result = response.json().get("result")
                if result is True:
                    return True
            except:
                pass

            # 如果失败,等待0.5秒后重试
            time.sleep(0.5)

        return False


if __name__ == "__main__":
    email_handler = EmailVerificationHandler()
    code = email_handler.get_verification_code()
    print(code)
