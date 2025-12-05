import os
import logging
import asyncio
from slack_sdk.oauth.installation_store.async_installation_store import AsyncInstallationStore
from slack_sdk.oauth.installation_store import Bot, Installation
from user_manager import get_db_connection

class CustomInstallationStore(AsyncInstallationStore):
    def __init__(self, client_id: str = None):
        self._logger = logging.getLogger(__name__)
        self.client_id = client_id

    async def async_save(self, installation: Installation):
        return await asyncio.to_thread(self.save, installation)

    async def async_find_bot(self, *, enterprise_id: str | None, team_id: str | None, is_enterprise_install: bool | None = False) -> Bot | None:
        return await asyncio.to_thread(self.find_bot, enterprise_id=enterprise_id, team_id=team_id, is_enterprise_install=is_enterprise_install)

    async def async_find_installation(self, *, enterprise_id: str | None, team_id: str | None, user_id: str | None = None, is_enterprise_install: bool | None = False) -> Installation | None:
        return await asyncio.to_thread(self.find_installation, enterprise_id=enterprise_id, team_id=team_id, user_id=user_id, is_enterprise_install=is_enterprise_install)

    async def async_delete_bot(self, *, enterprise_id: str | None, team_id: str | None) -> None:
        return await asyncio.to_thread(self.delete_bot, enterprise_id=enterprise_id, team_id=team_id)

    async def async_delete_installation(self, *, enterprise_id: str | None, team_id: str | None, user_id: str | None = None) -> None:
        return await asyncio.to_thread(self.delete_installation, enterprise_id=enterprise_id, team_id=team_id, user_id=user_id)

    def save(self, installation: Installation):
        conn, db_type = get_db_connection()
        cursor = conn.cursor()
        
        # Use provided client_id if missing from installation
        client_id = getattr(installation, 'client_id', None) or self.client_id
        
        try:
            if db_type == 'postgres':
                # Postgres upsert
                cursor.execute("""
                    INSERT INTO slack_installations (
                        client_id, app_id, enterprise_id, enterprise_name, enterprise_url,
                        team_id, team_name, bot_token, bot_id, bot_user_id, bot_scopes, bot_refresh_token, bot_token_expires_at,
                        user_id, user_token, user_scopes, user_refresh_token, user_token_expires_at,
                        incoming_webhook_url, incoming_webhook_channel, incoming_webhook_channel_id, incoming_webhook_configuration_url,
                        is_enterprise_install, token_type, installed_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, CURRENT_TIMESTAMP
                    )
                    ON CONFLICT (id) DO NOTHING; 
                """, (
                    client_id,
                    installation.app_id,
                    installation.enterprise_id,
                    installation.enterprise_name,
                    installation.enterprise_url,
                    installation.team_id,
                    installation.team_name,
                    installation.bot_token,
                    installation.bot_id,
                    installation.bot_user_id,
                    ",".join(installation.bot_scopes) if installation.bot_scopes else None,
                    installation.bot_refresh_token,
                    installation.bot_token_expires_at,
                    installation.user_id,
                    installation.user_token,
                    ",".join(installation.user_scopes) if installation.user_scopes else None,
                    installation.user_refresh_token,
                    installation.user_token_expires_at,
                    installation.incoming_webhook_url,
                    installation.incoming_webhook_channel,
                    installation.incoming_webhook_channel_id,
                    installation.incoming_webhook_configuration_url,
                    installation.is_enterprise_install,
                    installation.token_type
                ))
                # Note: The above ON CONFLICT is weak because we don't have a unique constraint on team_id in the CREATE TABLE yet (only index).
                # But for now, let's just insert. A better approach is to delete existing for this team_id first or add a unique constraint.
                # Let's do a delete-then-insert approach for simplicity and robustness across DBs, 
                # or just INSERT. Bolt usually handles latest.
                # Actually, let's delete old installation for this team to avoid duplicates.
                
            else:
                # SQLite
                cursor.execute("DELETE FROM slack_installations WHERE team_id = ?", (installation.team_id,))
                
                cursor.execute("""
                    INSERT INTO slack_installations (
                        client_id, app_id, enterprise_id, enterprise_name, enterprise_url,
                        team_id, team_name, bot_token, bot_id, bot_user_id, bot_scopes, bot_refresh_token, bot_token_expires_at,
                        user_id, user_token, user_scopes, user_refresh_token, user_token_expires_at,
                        incoming_webhook_url, incoming_webhook_channel, incoming_webhook_channel_id, incoming_webhook_configuration_url,
                        is_enterprise_install, token_type, installed_at
                    )
                    VALUES (
                        ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, CURRENT_TIMESTAMP
                    )
                """, (
                    client_id,
                    installation.app_id,
                    installation.enterprise_id,
                    installation.enterprise_name,
                    installation.enterprise_url,
                    installation.team_id,
                    installation.team_name,
                    installation.bot_token,
                    installation.bot_id,
                    installation.bot_user_id,
                    ",".join(installation.bot_scopes) if installation.bot_scopes else None,
                    installation.bot_refresh_token,
                    installation.bot_token_expires_at,
                    installation.user_id,
                    installation.user_token,
                    ",".join(installation.user_scopes) if installation.user_scopes else None,
                    installation.user_refresh_token,
                    installation.user_token_expires_at,
                    installation.incoming_webhook_url,
                    installation.incoming_webhook_channel,
                    installation.incoming_webhook_channel_id,
                    installation.incoming_webhook_configuration_url,
                    installation.is_enterprise_install,
                    installation.token_type
                ))

            # Also save to bots table for easier lookup
            if db_type == 'postgres':
                cursor.execute("DELETE FROM slack_bots WHERE team_id = %s", (installation.team_id,))
                cursor.execute("""
                    INSERT INTO slack_bots (
                        client_id, app_id, enterprise_id, enterprise_name,
                        team_id, team_name, bot_token, bot_id, bot_user_id, bot_scopes, bot_refresh_token, bot_token_expires_at,
                        is_enterprise_install, installed_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                """, (
                    client_id,
                    installation.app_id,
                    installation.enterprise_id,
                    installation.enterprise_name,
                    installation.team_id,
                    installation.team_name,
                    installation.bot_token,
                    installation.bot_id,
                    installation.bot_user_id,
                    ",".join(installation.bot_scopes) if installation.bot_scopes else None,
                    installation.bot_refresh_token,
                    installation.bot_token_expires_at,
                    installation.is_enterprise_install
                ))
            else:
                cursor.execute("DELETE FROM slack_bots WHERE team_id = ?", (installation.team_id,))
                cursor.execute("""
                    INSERT INTO slack_bots (
                        client_id, app_id, enterprise_id, enterprise_name,
                        team_id, team_name, bot_token, bot_id, bot_user_id, bot_scopes, bot_refresh_token, bot_token_expires_at,
                        is_enterprise_install, installed_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (
                    client_id,
                    installation.app_id,
                    installation.enterprise_id,
                    installation.enterprise_name,
                    installation.team_id,
                    installation.team_name,
                    installation.bot_token,
                    installation.bot_id,
                    installation.bot_user_id,
                    ",".join(installation.bot_scopes) if installation.bot_scopes else None,
                    installation.bot_refresh_token,
                    installation.bot_token_expires_at,
                    installation.is_enterprise_install
                ))
            
            conn.commit()
        except Exception as e:
            self._logger.error(f"Error saving installation: {e}")
            conn.rollback()
        finally:
            conn.close()

    def find_bot(self, *, enterprise_id: str | None, team_id: str | None, is_enterprise_install: bool | None = False) -> Bot | None:
        conn, db_type = get_db_connection()
        cursor = conn.cursor()
        
        try:
            query = "SELECT * FROM slack_bots WHERE team_id = %s" if db_type == 'postgres' else "SELECT * FROM slack_bots WHERE team_id = ?"
            # Note: In a real enterprise scenario, logic is more complex (checking enterprise_id), but for now assuming team_id is sufficient.
            cursor.execute(query, (team_id,))
            
            # Fetch column names to map correctly
            columns = [col[0] for col in cursor.description]
            row = cursor.fetchone()
            
            if row:
                data = dict(zip(columns, row))
                return Bot(
                    app_id=data.get('app_id'),
                    enterprise_id=data.get('enterprise_id'),
                    enterprise_name=data.get('enterprise_name'),
                    team_id=data.get('team_id'),
                    team_name=data.get('team_name'),
                    bot_token=data.get('bot_token'),
                    bot_id=data.get('bot_id'),
                    bot_user_id=data.get('bot_user_id'),
                    bot_scopes=data.get('bot_scopes').split(',') if data.get('bot_scopes') else [],
                    bot_refresh_token=data.get('bot_refresh_token'),
                    bot_token_expires_at=data.get('bot_token_expires_at'),
                    is_enterprise_install=bool(data.get('is_enterprise_install')),
                    installed_at=data.get('installed_at')
                )
            return None
        except Exception as e:
            self._logger.error(f"Error finding bot: {e}")
            return None
        finally:
            conn.close()

    def find_installation(self, *, enterprise_id: str | None, team_id: str | None, user_id: str | None = None, is_enterprise_install: bool | None = False) -> Installation | None:
        conn, db_type = get_db_connection()
        cursor = conn.cursor()
        
        try:
            query = "SELECT * FROM slack_installations WHERE team_id = %s" if db_type == 'postgres' else "SELECT * FROM slack_installations WHERE team_id = ?"
            if user_id:
                query += " AND user_id = %s" if db_type == 'postgres' else " AND user_id = ?"
                cursor.execute(query, (team_id, user_id))
            else:
                cursor.execute(query, (team_id,))
                
            columns = [col[0] for col in cursor.description]
            row = cursor.fetchone()
            
            if row:
                data = dict(zip(columns, row))
                return Installation(
                    app_id=data.get('app_id'),
                    enterprise_id=data.get('enterprise_id'),
                    enterprise_name=data.get('enterprise_name'),
                    enterprise_url=data.get('enterprise_url'),
                    team_id=data.get('team_id'),
                    team_name=data.get('team_name'),
                    bot_token=data.get('bot_token'),
                    bot_id=data.get('bot_id'),
                    bot_user_id=data.get('bot_user_id'),
                    bot_scopes=data.get('bot_scopes').split(',') if data.get('bot_scopes') else [],
                    bot_refresh_token=data.get('bot_refresh_token'),
                    bot_token_expires_at=data.get('bot_token_expires_at'),
                    user_id=data.get('user_id'),
                    user_token=data.get('user_token'),
                    user_scopes=data.get('user_scopes').split(',') if data.get('user_scopes') else [],
                    user_refresh_token=data.get('user_refresh_token'),
                    user_token_expires_at=data.get('user_token_expires_at'),
                    incoming_webhook_url=data.get('incoming_webhook_url'),
                    incoming_webhook_channel=data.get('incoming_webhook_channel'),
                    incoming_webhook_channel_id=data.get('incoming_webhook_channel_id'),
                    incoming_webhook_configuration_url=data.get('incoming_webhook_configuration_url'),
                    is_enterprise_install=bool(data.get('is_enterprise_install')),
                    token_type=data.get('token_type'),
                    installed_at=data.get('installed_at')
                )
            return None
        except Exception as e:
            self._logger.error(f"Error finding installation: {e}")
            return None
        finally:
            conn.close()
            
    def delete_bot(self, *, enterprise_id: str | None, team_id: str | None) -> None:
        conn, db_type = get_db_connection()
        cursor = conn.cursor()
        try:
            query = "DELETE FROM slack_bots WHERE team_id = %s" if db_type == 'postgres' else "DELETE FROM slack_bots WHERE team_id = ?"
            cursor.execute(query, (team_id,))
            conn.commit()
        finally:
            conn.close()

    def delete_installation(self, *, enterprise_id: str | None, team_id: str | None, user_id: str | None = None) -> None:
        conn, db_type = get_db_connection()
        cursor = conn.cursor()
        try:
            query = "DELETE FROM slack_installations WHERE team_id = %s" if db_type == 'postgres' else "DELETE FROM slack_installations WHERE team_id = ?"
            if user_id:
                query += " AND user_id = %s" if db_type == 'postgres' else " AND user_id = ?"
                cursor.execute(query, (team_id, user_id))
            else:
                cursor.execute(query, (team_id,))
            conn.commit()
        finally:
            conn.close()
