from datetime import datetime, timedelta
from django.db import transaction
from mi_app.models import Asignatura, Aula, Disponibilidad, Horario

def generar_horarios():
    asignaturas = Asignatura.objects.all()
    aulas_disponibles = list(Aula.objects.all())

    with transaction.atomic():
        for asignatura in asignaturas:
            minutos_disponibles = asignatura.intensidad_horaria  # minutos semanales
            docente = asignatura.docentes.first()
            jornada = asignatura.jornada

            if not docente:
                print(f"[ERROR] La asignatura '{asignatura.nombre}' no tiene docente asignado.")
                continue

            disponibilidades = Disponibilidad.objects.filter(docente=docente, jornada=jornada).order_by('dia', 'hora_inicio')

            for disponibilidad in disponibilidades:
                if minutos_disponibles <= 0:
                    break

                hora_inicio = disponibilidad.hora_inicio
                hora_actual = hora_inicio

                while minutos_disponibles > 0 and hora_actual < disponibilidad.hora_fin:
                    duracion_bloque = min(300, minutos_disponibles)  # máximo 90 minutos por bloque
                    hora_fin = (datetime.combine(datetime.today(), hora_actual) + timedelta(minutes=duracion_bloque)).time()

                    if hora_fin > disponibilidad.hora_fin:
                        break  # no hay suficiente espacio en este bloque de disponibilidad

                    aula_disponible = asignatura.aula
                    if not aula_disponible:
                        aula_disponible = next(
                            (a for a in aulas_disponibles if not Horario.objects.filter(
                                dia=disponibilidad.dia,
                                aula=a,
                                jornada=jornada,
                                hora_inicio__lt=hora_fin,
                                hora_fin__gt=hora_actual
                            ).exists()),
                            None
                        )

                    if not aula_disponible:
                        print(f"No hay aula disponible para {asignatura.nombre} en {disponibilidad.dia}.")
                        break

                    Horario.objects.create(
                        asignatura=asignatura,
                        docente=docente,
                        aula=aula_disponible,
                        dia=disponibilidad.dia,
                        jornada=jornada,
                        hora_inicio=hora_actual,
                        hora_fin=hora_fin
                    )

                    print(f"{asignatura.nombre} asignado a {docente} en {aula_disponible} el {disponibilidad.dia} - {hora_actual} a {hora_fin}")

                    minutos_disponibles -= duracion_bloque
                    hora_actual = hora_fin  # siguiente clase empieza donde terminó la anterior

    print("Horarios generados y guardados en la base de datos.")
