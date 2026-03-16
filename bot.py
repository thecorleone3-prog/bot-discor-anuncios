import discord
from discord.ext import commands, tasks
from discord.ui import View, Select, Modal, TextInput
import cv2
import asyncio
import numpy as np
from gtts import gTTS
import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
import os

ARG_TZ = ZoneInfo("America/Argentina/Buenos_Aires")

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

DATA_FILE = "data.json"

# =============================
# CONFIGURACION SERVIDOR
# =============================

DEFAULT_CONFIG = {
    "1480156876468387921": {

        "CANAL_CARGAS_ID": 1480156878150565924,
        "CANAL_PREMIOS_ID": 1480156877902843913,
        "CANAL_CREACION_ID": 1480156877902843914,

        "CANAL_AVISOS_ID": 1480947500037701765,
        "CANAL_VOZ_ID": 1480156877902843907,

        "panel_id": None,
        "panel_plantilla_id": None,
        "avisos": []
    }
}

# =============================
# LOAD DATA + MIGRACION
# =============================

def load_data():

    if not os.path.exists(DATA_FILE):

        with open(DATA_FILE,"w") as f:
            json.dump({"servers":DEFAULT_CONFIG},f,indent=4)

        return DEFAULT_CONFIG

    with open(DATA_FILE,"r") as f:
        data=json.load(f)

    servers=data["servers"]

    # MIGRAR AVISOS ANTIGUOS
    for guild_id,config in servers.items():

        for aviso in config.get("avisos",[]):

            if "activo" not in aviso:
                aviso["activo"]=True

            if "ultimo_ejecutado" not in aviso:
                aviso["ultimo_ejecutado"]=""

    return servers


def save_data(data):

    with open(DATA_FILE,"w") as f:
        json.dump({"servers":data},f,indent=4)


servers_config=load_data()

# =============================
# BOT
# =============================

intents=discord.Intents.default()
intents.message_content=True
intents.voice_states=True
intents.reactions = True

bot=commands.Bot(command_prefix="!",intents=intents)

# =============================
# PANEL TEXTO
# =============================

def construir_panel(guild_id):

    config=servers_config[guild_id]

    texto="📢 **PANEL DE AVISOS**\n\n"

    avisos=config["avisos"]

    if not avisos:
        texto+="No hay avisos programados"
        return texto

    for i,aviso in enumerate(avisos,1):

        estado="🟢" if aviso["activo"] else "🔴"

        texto+=f"{i}. {aviso['hora']} - {aviso['mensaje']} {estado}\n"

    return texto

# =============================
# MODAL AGREGAR
# =============================

class AgregarAvisoModal(Modal,title="Agregar aviso"):

    hora=TextInput(label="Hora",placeholder="18:00")
    mensaje=TextInput(label="Mensaje",style=discord.TextStyle.paragraph)

    async def on_submit(self,interaction:discord.Interaction):

        guild_id=str(interaction.guild.id)

        aviso={
            "hora":str(self.hora),
            "mensaje":str(self.mensaje),
            "activo":True,
            "ultimo_ejecutado":""
        }

        servers_config[guild_id]["avisos"].append(aviso)

        servers_config[guild_id]["avisos"].sort(key=lambda x:x["hora"])

        save_data(servers_config)

        await actualizar_panel(interaction.guild)

        await interaction.response.defer()

# =============================
# MODAL EDITAR
# =============================

class EditarAvisoModal(Modal):

    def __init__(self,index,guild_id):

        self.index=index
        self.guild_id=guild_id

        aviso=servers_config[guild_id]["avisos"][index]

        super().__init__(title="Editar aviso")

        self.hora=TextInput(label="Hora",default=aviso["hora"])
        self.mensaje=TextInput(label="Mensaje",default=aviso["mensaje"],style=discord.TextStyle.paragraph)

        self.add_item(self.hora)
        self.add_item(self.mensaje)

    async def on_submit(self,interaction:discord.Interaction):

        avisos=servers_config[self.guild_id]["avisos"]

        if self.index>=len(avisos):
            await interaction.response.defer()
            return

        aviso=avisos[self.index]

        aviso["hora"]=str(self.hora)
        aviso["mensaje"]=str(self.mensaje)

        avisos.sort(key=lambda x:x["hora"])

        save_data(servers_config)

        await actualizar_panel(interaction.guild)

        await interaction.response.defer()

# =============================
# SELECT AVISOS
# =============================

class AvisoSelect(Select):

    def __init__(self,guild_id):

        self.guild_id=guild_id

        avisos=servers_config[guild_id]["avisos"]

        options=[]

        if not avisos:
            options.append(discord.SelectOption(label="Sin avisos",value="none"))

        else:

            for i,aviso in enumerate(avisos):

                estado="🟢" if aviso["activo"] else "🔴"

                label=f"{aviso['hora']} - {aviso['mensaje'][:50]} {estado}"

                options.append(discord.SelectOption(label=label,value=str(i)))

        super().__init__(placeholder="Seleccionar aviso",options=options)

    async def callback(self,interaction:discord.Interaction):

        view=self.view

        if self.values[0]=="none":
            view.index=None
        else:
            view.index=int(self.values[0])

        await interaction.response.defer()

# =============================
# PANEL VIEW
# =============================

class PanelAvisosView(View):

    def __init__(self,guild_id):

        super().__init__(timeout=None)

        self.guild_id=guild_id
        self.index=None

        self.add_item(AvisoSelect(guild_id))

    @discord.ui.button(label="➕ Agregar",style=discord.ButtonStyle.green)
    async def agregar(self,interaction:discord.Interaction,button):

        await interaction.response.send_modal(AgregarAvisoModal())

    @discord.ui.button(label="✏️ Editar",style=discord.ButtonStyle.blurple)
    async def editar(self,interaction:discord.Interaction,button):

        if self.index is None:
            await interaction.response.defer()
            return

        await interaction.response.send_modal(EditarAvisoModal(self.index,self.guild_id))

    @discord.ui.button(label="🔄 Activar/Desactivar",style=discord.ButtonStyle.gray)
    async def toggle(self,interaction:discord.Interaction,button):

        avisos=servers_config[self.guild_id]["avisos"]

        if self.index is None or self.index>=len(avisos):
            await interaction.response.defer()
            return

        aviso=avisos[self.index]

        aviso["activo"]=not aviso["activo"]

        save_data(servers_config)

        await actualizar_panel(interaction.guild)

        await interaction.response.defer()

    @discord.ui.button(label="❌ Eliminar",style=discord.ButtonStyle.red)
    async def eliminar(self,interaction:discord.Interaction,button):

        avisos=servers_config[self.guild_id]["avisos"]

        if self.index is None or self.index>=len(avisos):
            await interaction.response.defer()
            return

        avisos.pop(self.index)

        save_data(servers_config)

        await actualizar_panel(interaction.guild)

        await interaction.response.defer()

# =============================
# ACTUALIZAR PANEL
# =============================

async def actualizar_panel(guild):

    guild_id=str(guild.id)

    config=servers_config[guild_id]

    canal=guild.get_channel(config["CANAL_AVISOS_ID"])

    texto=construir_panel(guild_id)

    view=PanelAvisosView(guild_id)

    panel_id=config.get("panel_id")

    if panel_id:

        try:

            msg=await canal.fetch_message(panel_id)

            await msg.edit(content=texto,view=view)

            return

        except:

            config["panel_id"]=None

    msg=await canal.send(texto,view=view)

    config["panel_id"]=msg.id

    save_data(servers_config)

# =============================
# COMANDO PANEL
# =============================

@bot.command()
async def panelavisos(ctx):

    guild_id=str(ctx.guild.id)

    if ctx.channel.id!=servers_config[guild_id]["CANAL_AVISOS_ID"]:
        return

    await actualizar_panel(ctx.guild)

    try:
        await ctx.message.delete()
    except:
        pass
    
# =============================
# LOOP AVISOS VOZ
# =============================

@tasks.loop(seconds=60)
async def check_scheduled_announcements():

    ahora=datetime.now(ARG_TZ).strftime("%H:%M")

    for guild_id,config in servers_config.items():

        for aviso in config["avisos"]:

            if not aviso["activo"]:
                continue

            if aviso["hora"]!=ahora:
                continue

            if aviso["ultimo_ejecutado"]==ahora:
                continue

            aviso["ultimo_ejecutado"]=ahora

            save_data(servers_config)

            guild=bot.get_guild(int(guild_id))

            canal=guild.get_channel(config["CANAL_VOZ_ID"])

            try:

                vc=guild.voice_client

                if vc is None:
                    vc=await canal.connect()

                archivo=f"aviso_{guild_id}.mp3"

                tts=gTTS(text=aviso["mensaje"],lang="es")

                tts.save(archivo)

                while vc.is_playing():
                    await asyncio.sleep(1)

                vc.play(
                    discord.FFmpegPCMAudio(
                        executable="ffmpeg",
                        source=archivo
                    )
                )

                while vc.is_playing():
                    await asyncio.sleep(1)

                os.remove(archivo)

            except Exception as e:

                print("Error aviso:",e)

# =============================
# READY
# =============================

@bot.event
async def on_ready():

    print("Bot listo")

    await asyncio.sleep(10)  # importante

    ahora = datetime.now(ARG_TZ)
    espera = 60 - ahora.second
    await asyncio.sleep(espera)

    if not check_scheduled_announcements.is_running():
        check_scheduled_announcements.start()

            
# =============================
# PANEL DE CONFIGURACION DE PLANTILLA
# =============================
async def enviar_temporal(interaction, texto, segundos=10):

    msg = await interaction.followup.send(texto)

    await asyncio.sleep(segundos)

    try:
        await msg.delete()
    except discord.NotFound:
        pass

class ConfigPlantillaView(discord.ui.View):
    def __init__(self, guild_id):
        super().__init__(timeout=None)
        self.guild_id = guild_id

    @discord.ui.button(label="Subir plantilla", style=discord.ButtonStyle.success)
    async def subir_plantilla(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Ahora envíe la imagen que desea usar como plantilla.", 
            delete_after=10)

        def check(m):
            return m.author == interaction.user and m.attachments and m.channel == interaction.channel

        try:
            msg = await bot.wait_for("message", check=check, timeout=120)
            archivo = msg.attachments[0]

            ruta = f"plantilla_{self.guild_id}.png"
            await archivo.save(ruta)

            servers_config[self.guild_id]["plantilla"] = ruta
            save_data(servers_config)

            await enviar_temporal(interaction, "✅ Plantilla guardada correctamente.")

            await asyncio.sleep(10)
            try:
                await msg.delete()
            except discord.NotFound:
                pass

        except asyncio.TimeoutError:
            await enviar_temporal(interaction, "❌ Tiempo agotado. No se subió ninguna plantilla.")

async def asegurar_conexion_voz(guild, canal_voz_id):

    canal = guild.get_channel(canal_voz_id)

    if canal is None:
        return None

    vc = guild.voice_client

    try:

        if vc is None or not vc.is_connected():
            vc = await canal.connect(reconnect=True)

        elif vc.channel.id != canal_voz_id:
            await vc.move_to(canal)

    except discord.ClientException:
        vc = guild.voice_client

    except Exception as e:
        print("Error conectando voz:", e)
        return None

    return vc

import io

async def reproducir_aviso(guild, canal_voz_id, texto):

    try:

        vc = await asegurar_conexion_voz(guild, canal_voz_id)

        if vc is None:
            return

        # generar audio en memoria
        tts = gTTS(text=texto, lang="es")

        audio_buffer = io.BytesIO()
        tts.write_to_fp(audio_buffer)
        audio_buffer.seek(0)

        while vc.is_playing():
            await asyncio.sleep(1)

        vc.play(
            discord.FFmpegPCMAudio(
                audio_buffer,
                pipe=True,
                executable="ffmpeg"
            )
        )

        while vc.is_playing():
            await asyncio.sleep(1)

    except Exception as e:
        print("Error aviso voz:", e)
async def actualizar_panel_plantilla(guild):

    guild_id = str(guild.id)
    config = servers_config[guild_id]

    canal = guild.get_channel(config["CANAL_AVISOS_ID"])

    view = ConfigPlantillaView(guild_id)

    panel_id = config.get("panel_plantilla_id")

    texto = "🧩 **PANEL DE PLANTILLAS**\n\nConfigurar plantilla para comprobantes."

    if panel_id:

        try:
            msg = await canal.fetch_message(panel_id)
            await msg.edit(content=texto, view=view)
            return

        except:
            config["panel_plantilla_id"] = None

    msg = await canal.send(texto, view=view)

    config["panel_plantilla_id"] = msg.id
    save_data(servers_config)
    
# =============================
# EVENTO PARA INSERTAR EL COMPROBANTE EN LA PLANTILLA
# =============================

def detectar_area_transparente(imagen):

    img = np.array(imagen)

    # Verificar que tenga canal alpha
    if img.shape[2] < 4:
        return None, None, "La plantilla no tiene transparencia (debe ser PNG con fondo transparente)."

    alpha = img[:, :, 3]

    # zona transparente
    mask = alpha == 0

    ys, xs = np.where(mask)

    if len(xs) == 0 or len(ys) == 0:
        return None, None, "No se encontró ninguna zona transparente en la plantilla."

    x_min = xs.min()
    x_max = xs.max()
    y_min = ys.min()
    y_max = ys.max()

    ancho = x_max - x_min
    alto = y_max - y_min

    # validar tamaño mínimo
    if ancho < 50 or alto < 50:
        return None, None, "La zona transparente es demasiado pequeña para colocar el comprobante."

    return (x_min, y_min, x_max, y_max), mask, None
@bot.event
async def on_reaction_add(reaction, user):

    guild = reaction.message.guild

    if guild is None:
        return

    guild_id = str(guild.id)
    config = servers_config[guild_id]

    # solo canal de cargas
    if reaction.message.channel.id != config["CANAL_CARGAS_ID"]:
        return

    # ignorar reacciones de usuarios (solo bots)
    if not user.bot:
        return

    # ignorar reacción 🤖
    ignorar_emojis = ["🤖", "⌛", "⏳"]
    if str(reaction.emoji) in ignorar_emojis:
        return

    await reproducir_aviso(
        guild,
        config["CANAL_VOZ_ID"],
        "Carga pendiente"
    )

@bot.event
async def on_message(message):

    if message.guild is None:
        return
    
    await bot.process_commands(message)
    guild_id = str(message.guild.id)
    config = servers_config[guild_id]

    # =========================
    # AVISO CANAL PREMIOS
    # =========================

    if message.channel.id == config["CANAL_PREMIOS_ID"]:

        # solo bots y sin imagenes
        if message.author.bot and not message.attachments:

            await reproducir_aviso(
                message.guild,
                config["CANAL_VOZ_ID"],
                "Premio en espera"
            )

    # LIMPIEZA CANAL AVISOS
    if message.channel.id == config["CANAL_AVISOS_ID"]:

        panel1 = config.get("panel_id")
        panel2 = config.get("panel_plantilla_id")

        # solo borrar mensajes de usuarios que no sean los paneles
        if not message.author.bot and message.id not in (panel1, panel2):
            
            try:
                await asyncio.sleep(10)
                await message.delete()
            except:
                pass

    guild_id = str(message.guild.id)
    canal_premios_id = servers_config[guild_id].get("CANAL_PREMIOS_ID")

    if message.channel.id != canal_premios_id:
        return
    
    if message.author.bot:
        return

    if message.attachments:
        if "plantilla" not in servers_config[guild_id]:
            await message.channel.send("❌ No hay plantilla definida para este servidor.")
            return

        import io
        from PIL import Image

        plantilla_path = servers_config[guild_id]["plantilla"]

        plantilla = Image.open(plantilla_path).convert("RGBA")
        comprobante_bytes = await message.attachments[0].read()
        comprobante = Image.open(io.BytesIO(comprobante_bytes)).convert("RGBA")

        # detectar área transparente
        area, mask, error = detectar_area_transparente(plantilla)
        
        if area is None:
            await message.channel.send(f"⚠️ {error}")
            return
        
        x1, y1, x2, y2 = area
        ancho = max(1, x2 - x1)
        alto = max(1, y2 - y1)

        # redimensionar comprobante
        comprobante = comprobante.resize((ancho, alto))
        
        from PIL import ImageFilter

        mask_crop = mask[y1:y2, x1:x2].astype("uint8") * 255

        # Reducir bordes blancos (erosión)
        kernel = np.ones((1,1), np.uint8)
        mask_crop = cv2.erode(mask_crop, kernel, iterations=3)

        mask_img = Image.fromarray(mask_crop, mode="L")

        # Suavizar bordes para que no se vean dentados
        mask_img = mask_img.filter(ImageFilter.GaussianBlur(0))

        comprobante.putalpha(mask_img)

        # pegar comprobante en pantalla del celular
        plantilla.paste(comprobante, (x1, y1), comprobante)

        salida_path = f"comprobante_{guild_id}.png"

        plantilla.save(salida_path)

        await message.channel.send(file=discord.File(salida_path))

        os.remove(salida_path)

# =============================
# COMANDO PARA ABRIR PANEL DE PLANTILLA
# =============================
@bot.command()
async def panelplantilla(ctx):

    guild_id = str(ctx.guild.id)
    config = servers_config[guild_id]

    if ctx.channel.id != config["CANAL_AVISOS_ID"]:
        return

    await actualizar_panel_plantilla(ctx.guild)

    try:
        await ctx.message.delete()
    except:
        pass  

# =============================
# RUN
# =============================

bot.run(TOKEN)
