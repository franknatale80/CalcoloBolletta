# CalcoloBolletta

Questo programma stima la bolletta della luce a partire dal consumo mensile in kWh.
            FUNZIONAMENTO:
            - Usa i corrispettivi presenti nelle bollette Octopus Fissa 12M (materia, trasporto, 
            oneri, imposte, bonus sociale), configurati nel file config_bolletta.json. 
            Inserisci il consumo mensile (kWh) e la potenza impegnata: il software calcola spesa materia energia, trasporto e gestione contatore, oneri di sistema, imposte (accisa + IVA) e applica il bonus sociale se                        selezionato.
            - L'opzione 'Importa bolletta (PDF)...' permette di leggere una bolletta Octopus e
              aggiornare automaticamente alcuni corrispettivi proponendo le variazioni trovate.
            - La sezione Storico mostra in basso i dati estratti dalle bollette PDF trovate
              nella cartella dell'applicazione.
            LIMITI:
            - Il risultato è una stima realistica basata sui parametri correnti; piccoli scostamenti
              rispetto alla bolletta reale possono dipendere da arrotondamenti e aggiornamenti ARERA.
